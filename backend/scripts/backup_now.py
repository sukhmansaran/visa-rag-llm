"""
Back up the database and the Chroma store outside the repo; keep the newest N; prove a backup restores (M0.16).

    cd backend
    python scripts/backup_now.py --label pre_cleanup        # back up now (then keep the newest N sets)
    python scripts/backup_now.py --list                     # what is there
    python scripts/backup_now.py --verify <file.dump>       # restore into a throwaway DB and compare row counts
    python scripts/backup_now.py --verify latest

A backup set is <db>_<label>_<stamp>.dump (pg_dump custom format), chroma_data_<label>_<stamp>/ and
<db>_<label>_<stamp>.manifest.json (Alembic revision, row count of every table, Chroma chunk count).
They go to PENDU_BACKUP_DIR, default `<folder containing the repo>/../db_backups`. Only sets named like this are
ever rotated away (PENDU_BACKUP_KEEP, default 20); other files there (account_exports/) are never touched.

Taken automatically before Alembic migrations of the dev database (alembic/env.py) and before scripted deletions
(remove_source_chunks.py, delete_account.py). Credentials come from settings and are never printed.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_BACKUP_DIR = BACKEND.parents[2] / "db_backups"
DEFAULT_KEEP = 20
RESTORE_CHECK_DB = "visa_chatbot_restore_check"
PG_BIN_CANDIDATES = [Path(r"C:\Program Files\PostgreSQL\16\bin"), Path("/usr/bin"), Path("/usr/local/bin")]
_STAMP = r"\d{8}_\d{6}"

# Row count of every table in one query (no psql loop)
_COUNT_SQL = (
    "SELECT table_name || '=' || (xpath('/row/c/text()', query_to_xml("
    "format('SELECT count(*) AS c FROM %I', table_name), false, true, '')))[1]::text "
    "FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
)


class PgToolError(RuntimeError):
    """A PostgreSQL client tool failed; the message carries the tool's own error output."""


def _run(args: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run a PostgreSQL tool; on failure raise with its stderr (the password travels in PGPASSWORD, never args)."""
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-1500:]
        raise PgToolError(f"{Path(args[0]).stem} failed (exit {result.returncode}): {detail}")
    return result


def _tool_major(name: str) -> int:
    """Major version of a client tool: 'pg_restore (PostgreSQL) 16.4' -> 16."""
    match = re.search(r"(\d+)(?:\.\d+)?", _run([_pg_tool(name), "--version"]).stdout)
    if not match:
        raise PgToolError(f"could not read the {name} version")
    return int(match.group(1))


def _server_major(url, env) -> int:
    return int(_psql(url, env, "SHOW server_version_num", database="postgres").strip()) // 10000


def _check_restore_tool(url, env) -> None:
    """
    A pg_restore newer than the server writes settings the server doesn't know (pg_restore 17+ sets
    transaction_timeout, which PostgreSQL 16 rejects), so restores fail with exit 1. Refuse up front with the fix.
    (Found 2026-10-24 when GitHub's ubuntu-latest image moved to newer PostgreSQL client tools.)
    """
    tool, server = _tool_major("pg_restore"), _server_major(url, env)
    if tool > server:
        raise PgToolError(
            f"pg_restore {tool} is newer than the PostgreSQL {server} server and its restores fail there. Install "
            f"the PostgreSQL {server} client tools (Windows: they come with PostgreSQL {server}; Ubuntu: "
            f"postgresql-client-{server}) and put them first on PATH.")


def _pg_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for folder in PG_BIN_CANDIDATES:
        for candidate in (folder / f"{name}.exe", folder / name):
            if candidate.exists():
                return str(candidate)
    raise FileNotFoundError(f"{name} not found on PATH or in {', '.join(map(str, PG_BIN_CANDIDATES))}")


def _connection():
    """(url, env with PGPASSWORD) for the configured database."""
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.DATABASE_URL)
    return url, dict(os.environ, PGPASSWORD=url.password or "")


def _pg_args(url, database: Optional[str] = None) -> List[str]:
    return ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username,
            "-d", database or url.database]


def _psql(url, env, sql: str, database: Optional[str] = None) -> str:
    return _run([_pg_tool("psql"), *_pg_args(url, database), "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], env).stdout


def table_counts(url, env, database: Optional[str] = None) -> Dict[str, int]:
    counts = {}
    for line in _psql(url, env, _COUNT_SQL, database).splitlines():
        if "=" in line:
            table, count = line.split("=", 1)
            counts[table] = int(count)
    return counts


def chroma_count(folder: Path) -> Optional[int]:
    db = Path(folder) / "chroma.sqlite3"
    if not db.exists():
        return None
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]


def backup_dir(override: Optional[Path] = None) -> Path:
    return Path(override or os.environ.get("PENDU_BACKUP_DIR") or DEFAULT_BACKUP_DIR)


def backup(label: str, backup_dir_override: Path = None, keep: Optional[int] = None) -> Tuple[Path, Path]:
    """Dump the DB, copy chroma_data, write the manifest, rotate. Returns (dump, chroma copy); raises on failure."""
    from app.core.config import settings

    folder = backup_dir(backup_dir_override)
    folder.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9_-]", "_", label)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    url, env = _connection()

    dump_path = folder / f"{url.database}_{label}_{stamp}.dump"
    counts = table_counts(url, env)
    _run([_pg_tool("pg_dump"), *_pg_args(url), "-Fc", "-f", str(dump_path)], env)
    listing = _run([_pg_tool("pg_restore"), "-l", str(dump_path)])
    if "TABLE DATA" not in listing.stdout:
        raise RuntimeError(f"Backup {dump_path} has no table data")

    chroma_source = Path(settings.CHROMA_PERSIST_DIRECTORY)
    if not chroma_source.is_absolute():
        chroma_source = BACKEND / chroma_source
    chroma_copy = folder / f"chroma_data_{label}_{stamp}"
    shutil.copytree(chroma_source, chroma_copy)

    manifest = {
        "created": datetime.datetime.now().isoformat(timespec="seconds"), "label": label, "database": url.database,
        "alembic_revision": (_psql(url, env, "SELECT version_num FROM alembic_version").strip() or None)
        if "alembic_version" in counts else None,  # a database built without Alembic has no revision
        "table_counts": counts, "chroma_chunks": chroma_count(chroma_copy),
        "dump": dump_path.name, "chroma_copy": chroma_copy.name,
    }
    dump_path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prune(folder, keep)
    return dump_path, chroma_copy


def backup_sets(folder: Path) -> List[Dict]:
    """
    Backup sets in `folder`, newest first: {"name", "stamp", "dump", "chroma", "manifest"} (paths may be None).
    Everything written by one backup shares its timestamp, so that is what groups a set.
    """
    sets: Dict[str, Dict] = {}
    for path in sorted(Path(folder).iterdir()) if Path(folder).exists() else []:
        match = re.search(rf"_({_STAMP})(\.dump|\.manifest\.json)?$", path.name)
        if not match:
            continue
        if path.is_dir() and path.name.startswith("chroma_data_"):
            kind = "chroma"
        elif path.is_file() and path.suffix == ".dump":
            kind = "dump"
        elif path.is_file() and path.name.endswith(".manifest.json"):
            kind = "manifest"
        else:
            continue
        stamp = match.group(1)
        entry = sets.setdefault(stamp, {"name": "", "stamp": stamp, "dump": None, "chroma": None, "manifest": None})
        entry[kind] = path
        if kind == "dump" or not entry["name"]:
            entry["name"] = re.sub(r"(\.dump|\.manifest\.json)$", "", path.name)
    return sorted(sets.values(), key=lambda s: s["stamp"], reverse=True)


def prune(folder: Path, keep: Optional[int] = None) -> List[str]:
    """Delete backup sets beyond the newest `keep`. Returns the names removed."""
    keep = keep if keep is not None else int(os.environ.get("PENDU_BACKUP_KEEP", DEFAULT_KEEP))
    removed = []
    for old in backup_sets(folder)[max(keep, 1):]:
        for kind in ("dump", "manifest"):
            if old[kind]:
                old[kind].unlink()
        if old["chroma"]:
            shutil.rmtree(old["chroma"])
        removed.append(old["name"])
    return removed


def verify_restore(dump_path: Path) -> Dict:
    """
    Restore `dump_path` into a throwaway database, compare every table's row count with the backup's manifest,
    drop the database. Returns {"ok", "tables", "mismatches", "manifest"}.
    """
    from app.core.database import DISPOSABLE_DATABASE_ALLOWLIST

    assert RESTORE_CHECK_DB in DISPOSABLE_DATABASE_ALLOWLIST
    url, env = _connection()
    manifest_path = Path(dump_path).with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None

    _check_restore_tool(url, env)
    _psql(url, env, f'DROP DATABASE IF EXISTS "{RESTORE_CHECK_DB}" WITH (FORCE)', database="postgres")
    _psql(url, env, f'CREATE DATABASE "{RESTORE_CHECK_DB}"', database="postgres")
    try:
        _run([_pg_tool("pg_restore"), *_pg_args(url, RESTORE_CHECK_DB), "--no-owner", str(dump_path)], env)
        restored = table_counts(url, env, RESTORE_CHECK_DB)
    finally:
        _psql(url, env, f'DROP DATABASE IF EXISTS "{RESTORE_CHECK_DB}" WITH (FORCE)', database="postgres")

    expected = (manifest or {}).get("table_counts")
    mismatches = {} if expected is None else {
        t: {"backup": expected.get(t), "restored": restored.get(t)}
        for t in set(expected) | set(restored) if expected.get(t) != restored.get(t)
    }
    return {"ok": expected is not None and not mismatches, "tables": restored, "mismatches": mismatches,
            "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="manual", help="word in the file names, e.g. pre_cleanup")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--keep", type=int, help=f"backup sets to keep (default PENDU_BACKUP_KEEP or {DEFAULT_KEEP})")
    parser.add_argument("--list", action="store_true", help="list backup sets")
    parser.add_argument("--verify", help="a .dump file (or 'latest'): restore it into a throwaway DB and compare")
    args = parser.parse_args()
    folder = backup_dir(args.backup_dir)

    if args.list:
        for s in backup_sets(folder):
            parts = [k for k in ("dump", "chroma", "manifest") if s[k]]
            print(f"{s['stamp']}  {s['name']:<55} {', '.join(parts)}")
        return 0

    if args.verify:
        dump = next((s["dump"] for s in backup_sets(folder) if s["dump"]), None) if args.verify == "latest" \
            else Path(args.verify)
        if dump is None or not Path(dump).exists():
            print("No such backup.")
            return 1
        result = verify_restore(Path(dump))
        total = sum(result["tables"].values())
        print(f"Restored {Path(dump).name}: {len(result['tables'])} tables, {total:,} rows")
        if result["manifest"] is None:
            print("No manifest for this backup (made before M0.16): restore works, counts not compared.")
            return 0
        for table, counts in sorted(result["mismatches"].items()):
            print(f"  MISMATCH {table}: backup {counts['backup']} vs restored {counts['restored']}")
        print("Row counts match the backup." if result["ok"] else "Row counts DIFFER from the backup.")
        return 0 if result["ok"] else 1

    dump_path, chroma_copy = backup(args.label, args.backup_dir, args.keep)
    print(f"Database: {dump_path} ({dump_path.stat().st_size:,} bytes)")
    print(f"Chroma:   {chroma_copy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
