"""
Data type definitions for the Crawler Pipeline.

Defines dataclasses used across crawler components and constants
for controlled vocabularies and validation.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FrontierEntry:
    """A URL entry in the crawl frontier queue."""
    url: str
    depth: int
    tier: int
    job_id: str
    seed_url: str
    allowed_domains: list[str]


@dataclass
class FetchResult:
    """Result of fetching a single URL."""
    url: str
    status_code: int
    raw_html: Optional[str]
    extracted_text: Optional[str]  # for PDFs
    headers: dict
    fetch_duration_ms: int
    used_playwright: bool


@dataclass
class ClassificationResult:
    """Result of page relevance classification."""
    is_relevant: bool
    reason: str
    matched_keywords: list[str]


@dataclass
class ExtractionResult:
    """Result of content extraction from HTML."""
    text: str
    content_hash: str
    structured_hints: dict  # JSON-LD, microdata, OG metadata
    title: Optional[str]


@dataclass
class CrawlJobConfig:
    """Configuration for a crawl job execution."""
    max_pages: int = 10000
    max_depth: int = 3
    tier_filter: Optional[list[int]] = None
    category_filter: Optional[list[str]] = None
    enable_llm_structuring: bool = True
    enable_embedding: bool = True


@dataclass
class TuitionFee:
    """Parsed tuition fee with currency."""
    amount: float
    currency: str  # ISO 4217: USD, EUR, GBP, CAD, AUD, SGD


@dataclass
class ExtractionConfig:
    """Portal-specific extraction configuration."""
    css_selectors: Optional[dict] = None
    json_ld_patterns: Optional[list[str]] = None
    html_patterns: Optional[dict] = None


@dataclass
class CachedResponse:
    """A cached HTTP response."""
    url: str
    status_code: int
    html: str
    headers: dict
    cached_at: float


# Controlled vocabulary for degree levels
DEGREE_LEVEL_VOCABULARY = [
    "bachelor", "master", "phd", "postgraduate_diploma",
    "short_course", "foundation", "certificate"
]

# Valid currency codes for tuition fees
VALID_CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "SGD"]
