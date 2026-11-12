from datetime import datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class FetchedPageReview(SQLModel, table=True):
    """
    Review queue (M5.5b, D2): a registry page fetched live whose text differs from the stored copy. It waits for an
    admin; nothing here is retrievable. Approving ingests exactly this text; rejecting deletes the text and keeps
    the hash, so the same content is not queued again (D7).
    """

    __tablename__ = "fetched_page_reviews"
    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_fetched_page_reviews_source_hash"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False,
                                            index=True))
    url: str = Field(max_length=2048)
    final_url: str = Field(max_length=2048)
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", sa_column=Column(Text, nullable=False))  # emptied once reviewed
    chars: int = Field(default=0)
    content_hash: str = Field(max_length=64, index=True)

    status: str = Field(default="pending", max_length=20, index=True)  # pending | approved | rejected
    outcome: Optional[str] = Field(default=None, max_length=500)       # what approving did, e.g. "12 chunks"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = Field(default=None)
    reviewed_by: Optional[int] = Field(default=None, sa_column=Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
