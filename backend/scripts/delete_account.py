"""
Export and/or delete a user account and everything it owns (M0.15; e.g. the legacy demo@pendu.app account).

    cd backend
    python scripts/delete_account.py --email demo@pendu.app                    # dry run: what would go
    python scripts/delete_account.py --email demo@pendu.app --export           # write a JSON export only
    python scripts/delete_account.py --email demo@pendu.app --export --apply   # export, back up, delete

Run by the owner. --apply backs up the database and chroma_data first (scripts/backup_now.py) and stops if that
fails. The export goes to <backups>/account_exports/ (outside the repo; it contains personal data). Rows other
people own that merely mention this user (as a reviewer) keep their row with the reference cleared.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.accounts import AccountError, data_summary, delete_user, export_user_data, find_user  # noqa: E402


def upload_dir() -> Path:
    folder = Path(getattr(settings, "UPLOAD_DIR", "uploads"))
    return folder if folder.is_absolute() else BACKEND / folder


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--export", action="store_true", help="write the account's data to a JSON file first")
    parser.add_argument("--apply", action="store_true", help="delete the account (default: dry run)")
    args = parser.parse_args()

    from backup_now import DEFAULT_BACKUP_DIR, backup

    async with AsyncSessionLocal() as db:
        try:
            user = await find_user(db, args.email)
        except AccountError as err:
            print(err)
            return 1
        summary = await data_summary(db, user.id)
        uploads = upload_dir() / str(user.id)
        print(f"Account {user.id}: {user.email} (admin={user.is_admin}, active={user.is_active})")
        for name, count in summary.items():
            print(f"  {name}: {count}")
        print(f"  uploads folder: {'present' if uploads.is_dir() else 'none'}")

        if args.export:
            out_dir = DEFAULT_BACKUP_DIR / "account_exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = out_dir / f"account_{user.id}_{stamp}.json"
            path.write_text(json.dumps(await export_user_data(db, user), indent=2, default=str), encoding="utf-8")
            print(f"Exported to {path}")

        if not args.apply:
            print("\nDry run: nothing deleted. Re-run with --apply to delete (add --export to keep a copy).")
            return 0

        dump, chroma = backup(f"pre_delete_account_{user.id}")
        print(f"Backed up: {dump}")
        try:
            affected = await delete_user(db, user, upload_dir())
        except Exception as err:
            await db.rollback()
            print(f"Not deleted (nothing changed): {err}")
            return 1
    print("Deleted: " + ", ".join(f"{k} {v}" for k, v in affected.items()) + "; and the account itself.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
