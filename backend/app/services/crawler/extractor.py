"""
Content Extractor for the Crawler Pipeline.

Dual-engine text extraction using Trafilatura (primary) and BeautifulSoup (fallback).
Supports portal-specific extraction configurations and structured metadata extraction
from JSON-LD, microdata, and Open Graph tags.
"""

import hashlib
import json
import logging
import re
from typing import Optional

from app.services.crawler.types import ExtractionConfig, ExtractionResult

logger = logging.getLogger(__name__)

# Minimum character threshold for Trafilatura output before falling back
_MIN_TRAFILATURA_CHARS = 100


class ContentExtractor:
    """Extracts clean text from HTML using Trafilatura + BeautifulSoup."""

    def extract(
        self,
        raw_html: str,
        url: str,
        portal_config: Optional[ExtractionConfig] = None,
    ) -> ExtractionResult:
        """Extract clean text from HTML.

        1. Try structured metadata (JSON-LD, microdata, OG) first.
        2. If portal_config provided, apply portal-specific selectors.
        3. Use Trafilatura as primary engine.
        4. Fall back to BeautifulSoup if Trafilatura returns < 100 chars.
        """
        structured_hints = self._extract_structured_metadata(raw_html)

        portal_data: dict = {}
        if portal_config:
            portal_data = self._apply_portal_config(raw_html, portal_config)
            structured_hints.update(portal_data)

        text = self._extract_trafilatura(raw_html, url)

        if not text or len(text) < _MIN_TRAFILATURA_CHARS:
            logger.debug("Trafilatura returned < %d chars, falling back to BS4", _MIN_TRAFILATURA_CHARS)
            text = self._extract_beautifulsoup(raw_html)

        title = self._extract_title(raw_html)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""

        return ExtractionResult(
            text=text or "",
            content_hash=content_hash,
            structured_hints=structured_hints,
            title=title,
        )

    def _extract_trafilatura(self, raw_html: str, url: str) -> Optional[str]:
        """Primary extraction via Trafilatura."""
        try:
            import trafilatura

            result = trafilatura.extract(
                raw_html,
                url=url,
                include_tables=True,
                include_links=False,
                include_comments=False,
                favor_precision=False,
                favor_recall=True,
            )
            return result
        except Exception:
            logger.warning("Trafilatura extraction failed for %s", url, exc_info=True)
            return None

    def _extract_beautifulsoup(self, raw_html: str) -> str:
        """Fallback extraction via BeautifulSoup."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(raw_html, "html.parser")

            # Remove non-content elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            # Collapse multiple blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except Exception:
            logger.warning("BeautifulSoup extraction failed", exc_info=True)
            return ""

    def _extract_structured_metadata(self, raw_html: str) -> dict:
        """Extract JSON-LD, microdata, and Open Graph metadata from HTML."""
        metadata: dict = {}
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(raw_html, "html.parser")

            # JSON-LD
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        metadata.setdefault("json_ld", []).extend(data)
                    else:
                        metadata.setdefault("json_ld", []).append(data)
                except (json.JSONDecodeError, TypeError):
                    continue

            # Open Graph
            og_tags: dict = {}
            for meta in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
                prop = meta.get("property", "")
                content = meta.get("content", "")
                if prop and content:
                    og_tags[prop] = content
            if og_tags:
                metadata["open_graph"] = og_tags

            # Basic microdata (itemprop attributes)
            micro: dict = {}
            for el in soup.find_all(attrs={"itemprop": True}):
                prop = el.get("itemprop", "")
                value = el.get("content") or el.get_text(strip=True)
                if prop and value:
                    micro[prop] = value
            if micro:
                metadata["microdata"] = micro

        except Exception:
            logger.warning("Structured metadata extraction failed", exc_info=True)

        return metadata

    def _apply_portal_config(self, raw_html: str, config: ExtractionConfig) -> dict:
        """Apply portal-specific CSS selectors or patterns."""
        result: dict = {}
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(raw_html, "html.parser")

            if config.css_selectors:
                for field_name, selector in config.css_selectors.items():
                    el = soup.select_one(selector)
                    if el:
                        result[field_name] = el.get_text(strip=True)

            if config.json_ld_patterns:
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string or "")
                        for pattern in config.json_ld_patterns:
                            if isinstance(data, dict) and data.get("@type") == pattern:
                                result.setdefault("matched_json_ld", []).append(data)
                    except (json.JSONDecodeError, TypeError):
                        continue

        except Exception:
            logger.warning("Portal config extraction failed", exc_info=True)

        return result

    def _extract_title(self, raw_html: str) -> Optional[str]:
        """Extract page title from HTML."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(raw_html, "html.parser")
            title_tag = soup.find("title")
            if title_tag:
                return title_tag.get_text(strip=True)
        except Exception:
            pass
        return None
