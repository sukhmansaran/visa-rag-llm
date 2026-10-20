"""
Account administration (M0.15): create or promote an admin, and export or delete a user's data.

Used by scripts/create_admin.py and scripts/delete_account.py, and meant for the in-app "delete my account"
(M6.6). Everything that references users.id is found from the models' foreign keys, so a table added later is
covered without editing this file:
  - rows the user owns are exported and deleted;
  - references to the user inside SOMEONE ELSE's row (a reviewer, "reviewed_by") are set to NULL instead.
Uploaded files live in uploads/<user_id>/ and are removed with the account.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.security import get_password_hash
from app.models.user import User

MIN_ADMIN_PASSWORD_LENGTH = 12

# Columns pointing at a user who is NOT the row's owner: cleared, never deleted
_REFERENCE_ONLY_COLUMNS = {"reviewer_id", "reviewed_by"}


class AccountError(ValueError):
    """A request that must not be carried out (unknown user, weak password, ...)."""


def user_references() -> List[Tuple[object, object, bool]]:
    """(table, column, owned) for every foreign key to users.id. owned=False: only a reference to the user."""
    import app.models  # noqa: F401  (register every model with SQLModel.metadata)

    refs = []
    for table in SQLModel.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "users" and fk.column.name == "id":
                refs.append((table, fk.parent, fk.parent.name not in _REFERENCE_ONLY_COLUMNS))
    return refs


async def find_user(db: AsyncSession, email: str) -> User:
    user = (await db.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if user is None:
        raise AccountError(f"No account with email {email}")
    return user


async def data_summary(db: AsyncSession, user_id: int) -> Dict[str, int]:
    """{"chat_messages.user_id": 82, ...}: rows that reference the user (non-zero only)."""
    summary = {}
    for table, column, _owned in user_references():
        count = (await db.execute(select(func.count()).select_from(table).where(column == user_id))).scalar() or 0
        if count:
            summary[f"{table.name}.{column.name}"] = count
    return summary


async def export_user_data(db: AsyncSession, user: User) -> dict:
    """The user's account (without the password hash) and every row they own, as JSON-ready data."""
    export = {
        "exported_at": datetime.utcnow().isoformat(timespec="seconds"),
        "account": {k: v for k, v in user.model_dump().items() if k != "hashed_password"},
        "tables": {},
    }
    for table, column, owned in user_references():
        if not owned:
            continue
        rows = (await db.execute(select(table).where(column == user.id))).mappings().all()
        if rows:
            export["tables"][table.name] = [dict(row) for row in rows]
    return export


async def delete_user(db: AsyncSession, user: User, upload_dir: Path) -> Dict[str, int]:
    """
    Delete the account and everything it owns, in one transaction; clear references to it in other people's
    rows; then remove its uploads folder. Returns {"table.column": rows affected}.
    """
    affected: Dict[str, int] = {}
    refs = user_references()
    for table, column, owned in refs:  # first, references in other people's rows
        if not owned:
            result = await db.execute(update(table).where(column == user.id).values({column.name: None}))
            if result.rowcount:
                affected[f"{table.name}.{column.name} (cleared)"] = result.rowcount
    for table, column, owned in reversed(refs):  # then the user's own rows, children before parents
        if owned:
            result = await db.execute(delete(table).where(column == user.id))
            if result.rowcount:
                affected[f"{table.name}.{column.name}"] = result.rowcount
    user_id = user.id
    await db.delete(user)
    await db.commit()

    folder = Path(upload_dir) / str(user_id)
    if folder.is_dir():
        shutil.rmtree(folder)
        affected["uploads folder"] = 1
    return affected


def check_admin_password(email: str, password: str) -> None:
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise AccountError(f"Use at least {MIN_ADMIN_PASSWORD_LENGTH} characters for an admin password")
    if email.split("@")[0].lower() in password.lower():
        raise AccountError("The password must not contain the email name")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9\W_]", password)):
        raise AccountError("Mix letters with digits or symbols")


async def create_or_promote_admin(db: AsyncSession, email: str, password: str = "") -> Tuple[User, str]:
    """
    Make `email` an admin. An existing account is promoted (its password unchanged unless one is given);
    a new one needs a password. Returns (user, "created" | "promoted" | "already_admin").
    """
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        if not password:
            raise AccountError("A new admin account needs a password")
        check_admin_password(email, password)
        user = User(email=email, hashed_password=get_password_hash(password), is_admin=True, is_active=True)
        db.add(user)
        outcome = "created"
    else:
        if password:
            check_admin_password(email, password)
            user.hashed_password = get_password_hash(password)
        outcome = "already_admin" if user.is_admin and not password else "promoted"
        user.is_admin = True
        user.is_active = True
    await db.commit()
    await db.refresh(user)
    return user, outcome


async def accounts_without_bcrypt(db: AsyncSession) -> List[str]:
    """Emails of accounts whose stored password is not a bcrypt hash (they can't log in; legacy data)."""
    rows = (await db.execute(select(User.email).where(~User.hashed_password.like("$2%")))).scalars().all()
    return list(rows)
