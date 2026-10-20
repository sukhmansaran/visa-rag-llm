"""
Create an admin account, or make an existing account an admin (M0.15).

    cd backend
    python scripts/create_admin.py --email you@example.com            # asks for a password (hidden)
    python scripts/create_admin.py --email you@example.com --promote  # existing account, keep its password

The password is typed at a hidden prompt, entered twice, and only its bcrypt hash is stored. It is never
written to code, logs or the shell history. At least 12 characters, mixing letters with digits or symbols.
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.accounts import AccountError, check_admin_password, create_or_promote_admin  # noqa: E402


def ask_password(email: str) -> str:
    for _ in range(3):
        first = getpass.getpass("New admin password (hidden): ")
        try:
            check_admin_password(email, first)
        except AccountError as err:
            print(f"  {err}")
            continue
        if getpass.getpass("Repeat it: ") == first:
            return first
        print("  The two entries differ.")
    raise SystemExit("No password set.")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--promote", action="store_true", help="existing account: grant admin, keep its password")
    args = parser.parse_args()

    password = "" if args.promote else ask_password(args.email)
    try:
        async with AsyncSessionLocal() as db:
            user, outcome = await create_or_promote_admin(db, args.email, password)
    except AccountError as err:
        print(f"Not done: {err}")
        return 1
    print({"created": f"Created admin account {user.email}.",
           "promoted": f"{user.email} is now an admin.",
           "already_admin": f"{user.email} was already an admin; nothing changed."}[outcome])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
