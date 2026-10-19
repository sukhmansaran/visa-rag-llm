"""
Back up the database (pg_dump, custom format) and the Chroma store, outside the repo.

    cd backend
    python scripts/backup_now.py --label pre_cleanup

Writes to PENDU_BACKUP_DIR, default `<folder containing the repo>/../db_backups` (D:/projects/llm chatbot/db_backups
here), as <db>_<label>_<timestamp>.dump and chroma_data_<label>_<timestamp>/. The dump is listed with pg_restore
afterwards to prove it is readable. Credentials come from settings and are never printed.
Used before any step that deletes data (scripts/remove_source_chunks.py); M0.16 automates it.
"""

import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_BACKUP_DIR = BACKEND.parents[2] / "db_backups"
PG_BIN_CANDIDATES = [Path(r"C:\Program Files\PostgreSQL\16\bin"), Path("/usr/bin"), Path("/usr/local/bin")]


def _pg_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for folder in PG_BIN_CANDIDATES:
        for candidate in (folder / f"{name}.exe", folder / name):
            if candidate.exists():
                return str(candidate)
    raise FileNotFoundError(f"{name} not found on PATH or in {', '.join(map(str, PG_BIN_CANDIDATES))}")


def backup(label: str, backup_dir: Path = None) -> Tuple[Path, Path]:
    """Dump the database and copy chroma_data. Returns (dump_path, chroma_copy). Raises on any failure."""
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    backup_dir = Path(backup_dir or os.environ.get("PENDU_BACKUP_DIR") or DEFAULT_BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    url = make_url(settings.DATABASE_URL)
    env = dict(os.environ, PGPASSWORD=url.password or "")

    dump_path = backup_dir / f"{url.database}_{label}_{stamp}.dump"
    subprocess.run([_pg_tool("pg_dump"), "-h", url.host or "localhost", "-p", str(url.port or 5432),
                    "-U", url.username, "-Fc", "-f", str(dump_path), url.database],
                   env=env, check=True, capture_output=True, text=True)
    listing = subprocess.run([_pg_tool("pg_restore"), "-l", str(dump_path)], check=True, capture_output=True, text=True)
    if "TABLE DATA" not in listing.stdout:
        raise RuntimeError(f"Backup {dump_path} has no table data")

    chroma_source = Path(settings.CHROMA_PERSIST_DIRECTORY)
    if not chroma_source.is_absolute():
        chroma_source = BACKEND / chroma_source
    chroma_copy = backup_dir / f"chroma_data_{label}_{stamp}"
    shutil.copytree(chroma_source, chroma_copy)
    return dump_path, chroma_copy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="manual", help="word in the file names, e.g. pre_cleanup")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    dump_path, chroma_copy = backup(args.label, args.backup_dir)
    print(f"Database: {dump_path} ({dump_path.stat().st_size:,} bytes)")
    print(f"Chroma:   {chroma_copy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
