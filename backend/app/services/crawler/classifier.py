"""
Page Classifier for the Crawler Pipeline.

Classifies pages as relevant or irrelevant based on keyword matching
against page title, URL path, and body text. Pages from known aggregator
portal domains are always classified as relevant.
"""

import re
from typing import Optional
from urllib.parse import urlparse

from app.services.crawler.types import ClassificationResult

# Default relevance keywords covering visa/immigration and education terms
DEFAULT_KEYWORDS: list[str] = [
    "visa",
    "immigration",
    "student visa",
    "work permit",
    "admission",
    "passport",
    "embassy",
    "consulate",
    "residence permit",
    "travel document",
    "program",
    "tuition",
    "scholarship",
    "intake",
    "degree",
    "bachelor",
    "master",
    "phd",
    "entry requirements",
    "university",
    "duration",
    "course",
]

# URL path patterns that indicate aggregator program pages
_AGGREGATOR_PROGRAM_PATTERNS: list[re.Pattern] = [
    re.compile(r"/programs?/", re.IGNORECASE),
    re.compile(r"/courses?/", re.IGNORECASE),
    re.compile(r"/study/", re.IGNORECASE),
    re.compile(r"/degrees?/", re.IGNORECASE),
    re.compile(r"/masters?/", re.IGNORECASE),
    re.compile(r"/bachelors?/", re.IGNORECASE),
    re.compile(r"/phd/", re.IGNORECASE),
    re.compile(r"/search", re.IGNORECASE),
    re.compile(r"/universities?/", re.IGNORECASE),
]

RELEVANCE_THRESHOLD = 3


class PageClassifier:
    """Classifies pages as relevant or irrelevant based on keyword matching."""

    def __init__(
        self,
        keywords: Optional[list[str]] = None,
        aggregator_domains: Optional[list[str]] = None,
    ) -> None:
        self.keywords = keywords if keywords is not None else DEFAULT_KEYWORDS
        self.aggregator_domains = aggregator_domains or []
        # Pre-compile keyword patterns for case-insensitive matching
        # Use word boundaries for single-word keywords; multi-word as-is
        self._keyword_patterns: list[tuple[str, re.Pattern]] = []
        for kw in self.keywords:
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            self._keyword_patterns.append((kw, pattern))

    def classify(
        self,
        url: str,
        title: str,
        body_text: str,
        portal_domain: Optional[str] = None,
    ) -> ClassificationResult:
        """Classify page relevance.

        If portal_domain is set and matches a known aggregator domain,
        the page is classified as relevant regardless of keyword count.
        Otherwise, checks URL path + title + body_text for keyword matches.

        Returns ClassificationResult with is_relevant, reason, matched_keywords.
        """
        # Check aggregator domain shortcut
        if portal_domain and self._is_known_aggregator(portal_domain):
            if self._is_aggregator_program_page(url, portal_domain):
                return ClassificationResult(
                    is_relevant=True,
                    reason=f"Aggregator program page from {portal_domain}",
                    matched_keywords=[],
                )
            # Even non-program pages from aggregator domains are relevant
            return ClassificationResult(
                is_relevant=True,
                reason=f"Page from known aggregator domain {portal_domain}",
                matched_keywords=[],
            )

        # Combine text sources for keyword matching
        parsed = urlparse(url)
        url_path = parsed.path.replace("/", " ").replace("-", " ").replace("_", " ")
        combined_text = f"{title} {url_path} {body_text}"

        # Find distinct keyword matches
        matched: list[str] = []
        for kw, pattern in self._keyword_patterns:
            if pattern.search(combined_text):
                matched.append(kw)

        is_relevant = len(matched) >= RELEVANCE_THRESHOLD

        if is_relevant:
            reason = f"Found {len(matched)} keywords: {', '.join(matched[:5])}"
        else:
            reason = f"Only {len(matched)} keyword(s) found (need {RELEVANCE_THRESHOLD})"

        return ClassificationResult(
            is_relevant=is_relevant,
            reason=reason,
            matched_keywords=matched,
        )

    def _is_aggregator_program_page(self, url: str, portal_domain: str) -> bool:
        """Check if URL matches known aggregator program page patterns.

        Returns True if the URL path matches patterns typical of
        program listing or detail pages on aggregator sites.
        """
        parsed = urlparse(url)
        path = parsed.path

        for pattern in _AGGREGATOR_PROGRAM_PATTERNS:
            if pattern.search(path):
                return True

        return False

    def _is_known_aggregator(self, domain: str) -> bool:
        """Check if domain is in the known aggregator domains list."""
        domain_lower = domain.lower()
        for agg_domain in self.aggregator_domains:
            if domain_lower == agg_domain.lower() or domain_lower.endswith(
                "." + agg_domain.lower()
            ):
                return True
        return False
