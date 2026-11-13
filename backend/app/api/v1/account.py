"""
The signed-in user's own account (M6.6, D7): a copy of everything stored about them, and deletion.

Deletion removes the account and every row it owns (profile, chats, documents, tracker, traces, uploads, paused agent
runs) through app/services/accounts.delete_user, the same code the owner's script uses. It asks for the password
again and the word DELETE, so a stolen session or a stray click can't do it. Administrator accounts are deleted with
scripts/delete_account.py instead, so the last administrator can't remove themselves from the browser.
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, verify_password
from app.models.user import User
from app.services import accounts

router = APIRouter(prefix="/account", tags=["Account"])

CONFIRM_WORD = "DELETE"


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)
    confirm: str = Field(..., max_length=20)


def upload_dir() -> Path:
    folder = Path(getattr(settings, "UPLOAD_DIR", "uploads"))
    return folder if folder.is_absolute() else Path(__file__).resolve().parents[3] / folder


@router.get("/export")
async def export_my_data(current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Everything stored about the caller: the account (never the password hash) and every row they own."""
    return jsonable_encoder(await accounts.export_user_data(db, current_user))


@router.post("/delete")
async def delete_my_account(request: DeleteAccountRequest, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Delete the caller's account and everything it owns. Cannot be undone."""
    if request.confirm != CONFIRM_WORD:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Type {CONFIRM_WORD} to confirm.")
    # 403, not 401: a 401 would make the app renew the session and send the wrong password again
    if not verify_password(request.password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Incorrect password.")
    if current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator accounts are deleted by the owner with scripts/delete_account.py.")
    affected = await accounts.delete_user(db, current_user, upload_dir())
    return {"deleted": True, "rows_removed": sum(affected.values())}
