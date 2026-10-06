from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON, UniqueConstraint

if TYPE_CHECKING:
    from app.models.aggregator_portal import AggregatorPortal


class ProgramRecord(SQLModel, table=True):
    """Structured academic program data extracted from aggregator pages."""

    __tablename__ = "program_records"
    __table_args__ = (
        UniqueConstraint("program_name", "university_name", name="uq_program_university"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portal_id: int = Field(foreign_key="aggregator_portals.id", index=True)
    document_id: int = Field(foreign_key="documents.id", index=True)
    source_url: str = Field(max_length=2048)

    program_name: str = Field(max_length=500, index=True)
    university_name: str = Field(max_length=500, index=True)
    degree_level: str = Field(max_length=50)  # controlled vocabulary
    tuition_fee: Optional[float] = Field(default=None)
    tuition_currency: Optional[str] = Field(default=None, max_length=3)
    duration: Optional[str] = Field(default=None, max_length=100)
    intake_dates: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    location_city: Optional[str] = Field(default=None, max_length=200)
    location_country: Optional[str] = Field(default=None, max_length=100, index=True)
    entry_requirements: Optional[str] = Field(default=None)
    language_of_instruction: Optional[str] = Field(default=None, max_length=50)
    application_deadline: Optional[str] = Field(default=None, max_length=100)
    scholarship_availability: Optional[bool] = Field(default=None)
    ucas_tariff_points: Optional[int] = Field(default=None)  # UCAS-specific
    university_ranking: Optional[int] = Field(default=None)  # Tier 4 sources
    ranking_year: Optional[int] = Field(default=None)

    needs_review: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    portal: "AggregatorPortal" = Relationship(back_populates="program_records")
