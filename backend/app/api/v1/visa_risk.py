"""
Visa Risk Summary v1 — The core product endpoint.

5 buckets, each scored 0-20:
  1. Academic Consistency
  2. Gap Years  
  3. Financial Readiness
  4. SOP Quality
  5. Application Timing

Total = sum of buckets (0-100).
75-100 = Low Risk, 50-74 = Medium Risk, <50 = High Risk.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.database import get_db
from app.core.security import get_current_user, get_demo_user
from app.models.user import User
from app.models.profile import Profile
from app.models.visa_risk import VisaRiskSummary, RiskBucket

router = APIRouter(prefix="/visa-risk", tags=["visa-risk"])


def _score_academic(profile: Profile) -> RiskBucket:
    """Bucket 1: Academic Consistency (0-20)."""
    score = 20

    # GPA check
    if profile.gpa is not None:
        if profile.gpa < 5.0:
            score -= 15
            return RiskBucket(
                name="Academic Consistency", score=max(0, score),
                flag="Very low GPA ({:.1f}) — visa officers see this as weak academic commitment.".format(profile.gpa),
                fix="Highlight upward trends, certifications, or relevant projects in your SOP to compensate.",
                fix_cta="sop_rewrite",
            )
        elif profile.gpa < 6.5:
            score -= 10
            return RiskBucket(
                name="Academic Consistency", score=max(0, score),
                flag="GPA below 6.5 — may raise questions about academic readiness for target universities.",
                fix="Address your GPA proactively in your SOP. Show growth and relevant skills.",
                fix_cta="sop_rewrite",
            )
        elif profile.gpa < 7.5:
            score -= 5
    else:
        score -= 8
        return RiskBucket(
            name="Academic Consistency", score=max(0, score),
            flag="GPA not provided — we cannot assess your academic standing.",
            fix="Complete your profile with accurate academic records.",
            fix_cta="complete_profile",
        )

    # Education level vs target mismatch
    if profile.education_level and profile.field_of_study:
        # Simple heuristic: if applying for master's but has no bachelor's indication, flag it
        pass  # Future: cross-check with target program level

    return RiskBucket(name="Academic Consistency", score=max(0, score), flag=None, fix=None)


def _score_gaps(profile: Profile) -> RiskBucket:
    """Bucket 2: Gap Years (0-20)."""
    score = 20

    # We infer gaps from work_experience being 0 or None
    # In a production system this would use graduation year vs current year
    work_exp = profile.work_experience

    if work_exp is None:
        score -= 12
        return RiskBucket(
            name="Gap Years", score=max(0, score),
            flag="Work experience not documented — any gap after graduation is a major red flag without explanation.",
            fix="Document your post-graduation activities clearly. Exam prep, freelance work, family reasons — all must be stated in the SOP.",
            fix_cta="sop_rewrite",
        )
    elif work_exp == 0:
        score -= 15
        return RiskBucket(
            name="Gap Years", score=max(0, score),
            flag="Zero work experience reported — visa officer will ask 'What have you been doing since graduation?'",
            fix="If you've been preparing for exams, volunteering, or doing independent projects, document it immediately in your SOP.",
            fix_cta="sop_rewrite",
        )

    return RiskBucket(name="Gap Years", score=max(0, score), flag=None, fix=None)


def _score_financial(profile: Profile) -> RiskBucket:
    """Bucket 3: Financial Readiness (0-20)."""
    score = 20

    # Check if tuition fee range preference exists (proxy for financial planning)
    has_financial_info = profile.tuition_fee_range is not None

    if not has_financial_info:
        score -= 10
        return RiskBucket(
            name="Financial Readiness", score=max(0, score),
            flag="No financial planning data provided — sponsor strength cannot be assessed.",
            fix="Upload bank statements, loan approval letters, or sponsor affidavits. Complete your financial profile.",
            fix_cta="upload_docs",
        )

    # Work experience as proxy for self-funding capacity
    if profile.work_experience is not None and profile.work_experience < 2:
        score -= 10
        return RiskBucket(
            name="Financial Readiness", score=max(0, score),
            flag="Limited work history with self-funding intent — visa officer may question fund source.",
            fix="Provide robust financial documentation: parent income proof, fixed deposits, or education loan sanction letter.",
            fix_cta="upload_docs",
        )

    return RiskBucket(name="Financial Readiness", score=max(0, score), flag=None, fix=None)


def _score_sop(profile: Profile) -> RiskBucket:
    """Bucket 4: SOP Quality (0-20)."""
    score = 20

    # Check if user has generated any SOP documents
    # We don't have direct access to documents table here, so use proxy:
    # If target_universities and field_of_study are empty = SOP will be generic
    has_target = profile.target_universities is not None and bool(profile.target_universities)
    has_field = profile.field_of_study is not None

    if not has_target and not has_field:
        score -= 15
        return RiskBucket(
            name="SOP Quality", score=max(0, score),
            flag="No target university or field specified — your SOP will be flagged as generic by visa officers.",
            fix="Get a risk-aligned SOP rewrite that specifically addresses your profile weaknesses and target program.",
            fix_cta="sop_rewrite",
        )
    elif not has_target:
        score -= 10
        return RiskBucket(
            name="SOP Quality", score=max(0, score),
            flag="No target universities specified — SOP cannot demonstrate genuine institutional fit.",
            fix="Select specific universities and get your SOP tailored to each program.",
            fix_cta="sop_rewrite",
        )
    elif not has_field:
        score -= 8
        return RiskBucket(
            name="SOP Quality", score=max(0, score),
            flag="Field of study not specified — your academic motivation will appear unclear.",
            fix="Complete your profile with your intended field. Then rewrite your SOP to align with it.",
            fix_cta="complete_profile",
        )

    return RiskBucket(name="SOP Quality", score=max(0, score), flag=None, fix=None)


def _score_timing(profile: Profile) -> RiskBucket:
    """Bucket 5: Application Timing (0-20)."""
    score = 20

    # Check intake periods
    intake = profile.intake_periods

    if not intake or len(intake) == 0:
        score -= 10
        return RiskBucket(
            name="Application Timing", score=max(0, score),
            flag="No target intake specified — you may be applying outside the ideal window.",
            fix="Set your target intake period and check university-specific deadlines immediately.",
            fix_cta="complete_profile",
        )

    return RiskBucket(name="Application Timing", score=max(0, score), flag=None, fix=None)


@router.get("/{profile_id}", response_model=VisaRiskSummary)
async def get_visa_risk_summary(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_demo_user),
) -> VisaRiskSummary:
    """
    THE CORE ENDPOINT.
    Returns the Visa Risk Summary with 5 scored buckets.
    """
    statement = select(Profile).where(Profile.id == profile_id)
    result = await db.exec(statement)
    profile = result.first()

    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Score each bucket
    buckets = [
        _score_academic(profile),
        _score_gaps(profile),
        _score_financial(profile),
        _score_sop(profile),
        _score_timing(profile),
    ]

    total_score = sum(b.score for b in buckets)

    # Classification
    if total_score >= 75:
        overall_risk = "Low"
    elif total_score >= 50:
        overall_risk = "Medium"
    else:
        overall_risk = "High"

    # Collect red flags
    red_flags = [b.flag for b in buckets if b.flag]

    # Top concern = lowest scoring bucket
    worst = min(buckets, key=lambda b: b.score)
    top_concern = worst.flag

    return VisaRiskSummary(
        overall_risk=overall_risk,
        score=total_score,
        buckets=buckets,
        red_flags=red_flags,
        top_concern=top_concern,
    )
