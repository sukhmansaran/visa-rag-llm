"""
Usage tracking and subscription tier management.
Enforces free-tier limits: 1 SOP export, 1 Risk Summary view.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel, Field, select
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from pydantic import BaseModel


# --- Pydantic Response Models ---

class UsageLimits(BaseModel):
    """Current usage state for a user."""
    tier: str  # 'free' or 'pro'
    sop_exports_used: int
    sop_exports_limit: int
    risk_views_used: int
    risk_views_limit: int
    can_export_sop: bool
    can_view_risk: bool
    can_mock_interview: bool


class UpgradeTier(BaseModel):
    """Available upgrade options."""
    sop_rewrite_price: str
    pro_monthly_price: str
    currency: str


# --- In-memory usage store (replace with DB table in production) ---
# For MVP speed, we track usage in-memory. In production, this becomes a SQL table.
_user_usage: dict[int, dict] = {}


def _get_usage(user_id: int) -> dict:
    if user_id not in _user_usage:
        _user_usage[user_id] = {
            "tier": "free",
            "sop_exports": 0,
            "risk_views": 0,
        }
    return _user_usage[user_id]


# --- Free tier limits ---
FREE_SOP_LIMIT = 1
FREE_RISK_LIMIT = 1


router = APIRouter(prefix="/subscription", tags=["subscription"])


@router.get("/usage", response_model=UsageLimits)
async def get_usage(
    current_user: User = Depends(get_current_user),
):
    """Get the current user's usage limits and remaining quota."""
    usage = _get_usage(current_user.id)
    is_pro = usage["tier"] == "pro"
    
    sop_used = usage["sop_exports"]
    risk_used = usage["risk_views"]
    
    return UsageLimits(
        tier=usage["tier"],
        sop_exports_used=sop_used,
        sop_exports_limit=999 if is_pro else FREE_SOP_LIMIT,
        risk_views_used=risk_used,
        risk_views_limit=999 if is_pro else FREE_RISK_LIMIT,
        can_export_sop=is_pro or sop_used < FREE_SOP_LIMIT,
        can_view_risk=is_pro or risk_used < FREE_RISK_LIMIT,
        can_mock_interview=is_pro or risk_used > 0,  # Must have viewed risk at least once
    )


@router.post("/track-sop-export")
async def track_sop_export(
    current_user: User = Depends(get_current_user),
):
    """Track an SOP export event. Returns 403 if limit exceeded."""
    usage = _get_usage(current_user.id)
    
    if usage["tier"] != "pro" and usage["sop_exports"] >= FREE_SOP_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free SOP export limit reached. Upgrade to Pro for unlimited exports."
        )
    
    usage["sop_exports"] += 1
    return {"status": "tracked", "sop_exports_used": usage["sop_exports"]}


@router.post("/track-risk-view")
async def track_risk_view(
    current_user: User = Depends(get_current_user),
):
    """Track a Visa Risk Summary view. Returns 403 if limit exceeded."""
    usage = _get_usage(current_user.id)
    
    if usage["tier"] != "pro" and usage["risk_views"] >= FREE_RISK_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free Risk Summary limit reached. Upgrade to Pro for unlimited access."
        )
    
    usage["risk_views"] += 1
    return {"status": "tracked", "risk_views_used": usage["risk_views"]}


@router.get("/pricing", response_model=UpgradeTier)
async def get_pricing():
    """Return current pricing for upgrade options."""
    return UpgradeTier(
        sop_rewrite_price="₹999",
        pro_monthly_price="₹499/month",
        currency="INR",
    )


@router.post("/upgrade-to-pro")
async def upgrade_to_pro(
    current_user: User = Depends(get_current_user),
):
    """
    Simulate upgrading user to Pro tier.
    In production, this is called AFTER Razorpay payment confirmation webhook.
    """
    usage = _get_usage(current_user.id)
    usage["tier"] = "pro"
    return {"status": "upgraded", "tier": "pro"}
