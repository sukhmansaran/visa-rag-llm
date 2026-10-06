"""
Pydantic schemas for the Crawler Pipeline API.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CrawlJobCreate(BaseModel):
    seed_urls: list[str] = Field(..., min_length=1)
    max_pages: int = Field(default=10000, ge=1)
    max_depth: int = Field(default=3, ge=1, le=10)
    tier: int = Field(default=3, ge=1, le=5)
    allowed_domains: Optional[list[str]] = None
    portal_domain: Optional[str] = None
    use_playwright: bool = False
    enable_llm_structuring: bool = True
    enable_embedding: bool = True


class CrawlJobResponse(BaseModel):
    job_id: str
    status: str
    pages_crawled: int = 0
    pages_relevant: int = 0
    pages_stored: int = 0
    pages_failed: int = 0
    pages_duplicate: int = 0
    pages_robots_blocked: int = 0
    frontier_pending: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CrawlJobStatusResponse(BaseModel):
    job_id: str
    status: str
    seed_urls: list[str] = []
    pages_crawled: int = 0
    pages_relevant: int = 0
    pages_stored: int = 0
    pages_failed: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    paused_at: Optional[str] = None


class PortalCreate(BaseModel):
    name: str = Field(..., max_length=255)
    tier: int = Field(..., ge=1, le=5)
    base_domains: list[str]
    category: str = Field(default="aggregator", max_length=50)
    throttle_rps: float = Field(default=0.5, gt=0)
    requires_js: bool = False
    extraction_config: Optional[dict] = None


class PortalResponse(BaseModel):
    id: int
    name: str
    tier: int
    base_domains: list[str]
    category: str
    throttle_rps: float
    requires_js: bool
    is_active: bool
    created_at: Optional[str] = None


class SeedURLCreate(BaseModel):
    portal_id: int
    url: str = Field(..., max_length=2048)
    max_depth: int = Field(default=3, ge=1, le=10)
    allowed_domains: list[str] = []
    crawl_schedule: str = Field(default="weekly")


class SeedURLResponse(BaseModel):
    id: int
    portal_id: int
    url: str
    max_depth: int
    allowed_domains: list[str]
    crawl_schedule: str
    is_active: bool
    last_crawled_at: Optional[str] = None


class SeedURLUpdate(BaseModel):
    max_depth: Optional[int] = None
    allowed_domains: Optional[list[str]] = None
    crawl_schedule: Optional[str] = None
    is_active: Optional[bool] = None
