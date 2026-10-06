from typing import List, Optional
from pydantic import BaseModel, Field


class RiskBucket(BaseModel):
    """One of the 5 risk evaluation areas."""
    name: str
    score: int = Field(..., ge=0, le=20, description="Score out of 20 for this bucket")
    max_score: int = 20
    flag: Optional[str] = Field(default=None, description="Red flag if score is low")
    fix: Optional[str] = Field(default=None, description="Actionable fix for this flag")
    fix_cta: Optional[str] = Field(default=None, description="CTA type: 'sop_rewrite', 'mock_interview', 'upload_docs', 'complete_profile'")


class VisaRiskSummary(BaseModel):
    """The verdict. 5 buckets, total score, risk level."""
    overall_risk: str = Field(..., description="'Low', 'Medium', or 'High'")
    score: int = Field(..., description="Total score out of 100")
    buckets: List[RiskBucket] = Field(..., description="The 5 scored risk buckets")
    red_flags: List[str] = Field(default_factory=list, description="All flags across buckets")
    top_concern: Optional[str] = Field(default=None, description="The single worst issue")
