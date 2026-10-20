"""
Backups (M0.16): sets are grouped and rotated safely, and a backup really restores with the same row counts.
The round trip runs pg_dump/pg_restore against the TEST database; it is skipped if the PostgreSQL client
tools aren't installed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import backup_now  # noqa: E402

from app.models.source import Source  # noqa: E402


def make_set(folder: Path, label: str, stamp: str, chroma=True, manifest=True):
    (folder / f"visa_chatbot_{label}_{stamp}.dump").write_bytes(b"dump")
    if chroma:
        (folder / f"chroma_data_{label}_{stamp}").mkdir()
    if manifest:
        (folder / f"visa_chatbot_{label}_{stamp}.manifest.json").write_text("{}", encoding="utf-8")


def test_sets_are_grouped_by_timestamp_newest_first(tmp_path):
    make_set(tmp_path, "pre_reingest", "20261019_223909")
    make_set(tmp_path, "rev008", "20261012_150910", chroma=False, manifest=False)  # an old dump-only backup
    sets = backup_now.backup_sets(tmp_path)
    assert [s["stamp"] for s in sets] == ["20261019_223909", "20261012_150910"]
    assert sets[0]["dump"] and sets[0]["chroma"] and sets[0]["manifest"]
    assert sets[0]["name"] == "visa_chatbot_pre_reingest_20261019_223909"
    assert sets[1]["chroma"] is None


def test_rotation_keeps_the_newest_and_never_touches_other_files(tmp_path):
    for day in range(1, 6):
        make_set(tmp_path, "auto", f"2026101{day}_120000")
    (tmp_path / "account_exports").mkdir()
    (tmp_path / "account_exports" / "account_1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")

    removed = backup_now.prune(tmp_path, keep=2)

    assert len(removed) == 3
    assert [s["stamp"] for s in backup_now.backup_sets(tmp_path)] == ["20261015_120000", "20261014_120000"]
    assert not list(tmp_path.glob("*20261011*"))  # dump, chroma copy and manifest all gone
    assert (tmp_path / "account_exports" / "account_1.json").exists() and (tmp_path / "notes.txt").exists()


def test_rotation_always_keeps_at_least_one(tmp_path):
    make_set(tmp_path, "auto", "20261015_120000")
    assert backup_now.prune(tmp_path, keep=0) == []


def _pg_tools_available() -> bool:
    try:
        for tool in ("pg_dump", "pg_restore", "psql"):
            backup_now._pg_tool(tool)
        return True
    except FileNotFoundError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _pg_tools_available(), reason="PostgreSQL client tools not installed")
async def test_a_backup_restores_with_the_same_row_counts(db_session, tmp_path):
    from app.core.config import settings
    assert settings.DATABASE_URL.endswith("_test")  # conftest points the app at the test database

    db_session.add_all([Source(url=f"https://www.canada.ca/{i}.html", name=str(i), source_type="official")
                        for i in range(3)])
    await db_session.commit()

    dump, chroma = backup_now.backup("pytest_round_trip", tmp_path, keep=5)
    manifest = json.loads(dump.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["table_counts"]["sources"] == 3 and chroma.exists()

    result = backup_now.verify_restore(dump)
    assert result["ok"] and result["tables"]["sources"] == 3

    # a backup whose contents don't match its manifest is reported, not passed
    manifest["table_counts"]["sources"] = 99
    dump.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    tampered = backup_now.verify_restore(dump)
    assert not tampered["ok"] and tampered["mismatches"]["sources"] == {"backup": 99, "restored": 3}
