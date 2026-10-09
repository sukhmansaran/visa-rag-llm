"""
CanadaNormalizer: Deterministic extraction and normalization for Canadian immigration documents.

Features:
- Deterministic extraction: identical input produces identical normalized text and hash.
- Strips government boilerplate: WET-BOEW / GCWeb navigation, search bars, breadcrumbs, footers, and scripts.
- Preserves statutory and legal semantics: headings, paragraphs, lists, markdown tables, dollar amounts,
  IRPR section markers, dates, benchmark levels, and relevant URLs.
- Unicode and whitespace normalization (NFKC, zero-width space stripping, line-ending unification).
- Metadata extraction: title, canonical URL, language.
- Short/empty content detection with configurable thresholds.
- Purely deterministic; makes zero network or LLM calls.
"""

import hashlib
import logging
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """Base exception for normalization failures."""
    pass


class ContentTooShortError(NormalizationError):
    """Raised when extracted content is suspiciously short or empty."""
    pass


@dataclass
class NormalizedDocument:
    """Immutable representation of normalized text and extracted metadata."""
    text: str
    content_hash: str
    title: Optional[str] = None
    canonical_url: Optional[str] = None
    language: Optional[str] = None
    raw_byte_count: int = 0
    normalized_char_count: int = 0
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class CanadaNormalizer:
    """
    Deterministic normalizer for official Canadian immigration HTML and text pages.
    """

    DEFAULT_MIN_CHARS = 50

    # Elements completely removed prior to content extraction
    UNWANTED_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "video",
        "audio",
        "iframe",
        "embed",
        "object",
        "form",
        "input",
        "button",
        "select",
        "textarea",
        "dialog",
    }

    # Boilerplate containers common to Canada.ca (GCWeb / WET-BOEW framework)
    BOILERPLATE_TAGS = {"header", "footer", "nav"}

    BOILERPLATE_SELECTORS = [
        # Breadcrumbs
        "#wb-bc",
        ".breadcrumb",
        ".breadcrumbs",
        # Search and menu headers
        "#wb-srch",
        "#wb-sm",
        "#wb-glb-mn",
        "#wb-g-sec",
        ".gc-sub-header",
        ".gc-main-footer",
        # Page details / feedback widget
        ".pagedetails",
        ".gc-pg-hlp",
        # Skip to main content links
        ".wb-sl",
        ".wb-inv",
        "#wb-head",
        "#wb-foot",
    ]

    def __init__(self, min_char_count: int = DEFAULT_MIN_CHARS, strict: bool = True):
        self.min_char_count = min_char_count
        self.strict = strict

    def normalize(
        self,
        content: str | bytes,
        url: Optional[str] = None,
        content_type: str = "text/html",
    ) -> NormalizedDocument:
        """
        Convenience dispatcher normalizing HTML or plain text based on content type.
        """
        if "html" in (content_type or "").lower() or (isinstance(content, str) and "<html" in content.lower()):
            return self.normalize_html(content, source_url=url)
        return self.normalize_text(content, source_url=url)

    def normalize_html(
        self,
        html_content: str | bytes,
        source_url: Optional[str] = None,
    ) -> NormalizedDocument:
        """
        Extract and normalize meaningful content from official HTML.

        Args:
            html_content: Raw HTML as string or bytes.
            source_url: Optional source URL for provenance logging.

        Returns:
            NormalizedDocument with clean markdown, hash, and metadata.
        """
        raw_bytes = (
            html_content.encode("utf-8")
            if isinstance(html_content, str)
            else html_content
        )
        raw_byte_count = len(raw_bytes)
        warnings: List[str] = []

        if not raw_bytes.strip():
            if self.strict:
                raise ContentTooShortError("Received empty HTML content.")
            warnings.append("Empty HTML content received.")
            return NormalizedDocument(
                text="",
                content_hash=hashlib.sha256(b"").hexdigest(),
                raw_byte_count=0,
                normalized_char_count=0,
                warnings=warnings,
            )

        soup = BeautifulSoup(raw_bytes, "html.parser")

        # 1. Extract metadata before decomposition
        title = self._extract_title(soup)
        canonical_url = self._extract_canonical_url(soup)
        language = self._extract_language(soup)
        date_modified = self._extract_date_modified(soup)

        # 2. Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 3. Remove non-content tags
        for tag in soup.find_all(self.UNWANTED_TAGS):
            tag.decompose()

        # 4. Remove boilerplate containers and GCWeb selectors
        for tag in soup.find_all(self.BOILERPLATE_TAGS):
            tag.decompose()

        for selector in self.BOILERPLATE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        # 5. Locate primary content container if present (Canada.ca standard: <main property="mainContentOfPage"> or <main>)
        main_content = (
            soup.find("main", attrs={"property": "mainContentOfPage"})
            or soup.find("main")
            or soup.find("div", id="wb-cont")
            or soup.find("body")
            or soup
        )

        # 6. Transform content into structured Markdown
        extracted_text = self._element_to_markdown(main_content)

        # 7. Apply deterministic text sanitization
        normalized_text = self._clean_whitespace_and_unicode(extracted_text)
        char_count = len(normalized_text)

        # 8. Length validation & anomaly detection
        if raw_byte_count >= 5000 and char_count < self.min_char_count:
            warnings.append(
                f"Possible extraction anomaly: large raw HTML ({raw_byte_count} bytes) "
                f"produced suspiciously short text ({char_count} chars)."
            )

        if char_count < self.min_char_count:
            msg = (
                f"Normalized content is suspiciously short ({char_count} chars < {self.min_char_count} threshold) "
                f"for URL: {source_url or 'unknown'}"
            )
            if self.strict:
                raise ContentTooShortError(msg)
            warnings.append(msg)

        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

        return NormalizedDocument(
            text=normalized_text,
            content_hash=content_hash,
            title=title,
            canonical_url=canonical_url,
            language=language,
            raw_byte_count=raw_byte_count,
            normalized_char_count=char_count,
            warnings=warnings,
            metadata={
                "source_url": source_url,
                "has_title": bool(title),
                "has_canonical": bool(canonical_url),
                "date_modified": date_modified,
            },
        )

    def normalize_text(
        self,
        plain_text: str | bytes,
        source_url: Optional[str] = None,
    ) -> NormalizedDocument:
        """
        Normalize raw plain-text content deterministically.
        """
        raw_bytes = (
            plain_text.encode("utf-8")
            if isinstance(plain_text, str)
            else plain_text
        )
        raw_byte_count = len(raw_bytes)
        text_str = raw_bytes.decode("utf-8", errors="replace")

        warnings: List[str] = []
        normalized_text = self._clean_whitespace_and_unicode(text_str)
        char_count = len(normalized_text)

        if char_count < self.min_char_count:
            msg = f"Plain text content length ({char_count}) is below minimum threshold ({self.min_char_count})"
            if self.strict:
                raise ContentTooShortError(msg)
            warnings.append(msg)

        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

        return NormalizedDocument(
            text=normalized_text,
            content_hash=content_hash,
            title=None,
            canonical_url=None,
            language=None,
            raw_byte_count=raw_byte_count,
            normalized_char_count=char_count,
            warnings=warnings,
            metadata={"source_url": source_url},
        )

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract clean document title."""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = unicodedata.normalize("NFKC", title_tag.get_text()).strip()
            # Remove standard Canada.ca title suffix if present
            title = re.sub(r"\s*-\s*Canada\.ca$", "", title, flags=re.IGNORECASE)
            return title.strip() or None
        # Fallback to h1
        h1_tag = soup.find("h1")
        if h1_tag:
            return unicodedata.normalize("NFKC", h1_tag.get_text()).strip() or None
        return None

    def _extract_canonical_url(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract and validate canonical URL from link tag."""
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            raw_href = str(link["href"]).strip()
            try:
                parsed = urllib.parse.urlsplit(raw_href)
                scheme = (parsed.scheme or "").lower()
                if scheme in ("http", "https") and parsed.hostname and not (parsed.username or parsed.password):
                    return raw_href
            except Exception:
                pass
        return None

    def _extract_date_modified(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract official modification date from WET-BOEW / Canada.ca metadata if present."""
        time_tag = soup.find("time", attrs={"property": "dateModified"}) or soup.find(
            "time", attrs={"itemprop": "dateModified"}
        )
        if time_tag and time_tag.get_text():
            return time_tag.get_text().strip()
        return None

    def _extract_language(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract language code from html tag or meta tag."""
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            return str(html_tag["lang"]).strip().lower()
        meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
        if meta_lang and meta_lang.get("content"):
            return str(meta_lang["content"]).strip().lower()
        return None

    def _element_to_markdown(self, element: Tag) -> str:
        """
        Recursively convert DOM subtree to semantic Markdown while preserving
        statutory figures, table columns, lists, and headings.
        """
        parts: List[str] = []

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    parts.append(text)
            elif isinstance(child, Tag):
                tag_name = child.name.lower()

                # Headings
                if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    level = int(tag_name[1])
                    heading_text = self._element_to_markdown(child).strip()
                    if heading_text:
                        parts.append(f"\n\n{'#' * level} {heading_text}\n\n")

                # Paragraphs and blockquotes
                elif tag_name == "p":
                    p_text = self._element_to_markdown(child).strip()
                    if p_text:
                        parts.append(f"\n\n{p_text}\n\n")
                elif tag_name == "blockquote":
                    quote_text = self._element_to_markdown(child).strip()
                    if quote_text:
                        quoted = "\n".join(f"> {line}" for line in quote_text.splitlines())
                        parts.append(f"\n\n{quoted}\n\n")

                # Lists
                elif tag_name in ("ul", "ol"):
                    list_md = self._list_to_markdown(child, is_ordered=(tag_name == "ol"))
                    if list_md:
                        parts.append(f"\n\n{list_md}\n\n")

                # Tables
                elif tag_name == "table":
                    table_md = self._table_to_markdown(child)
                    if table_md:
                        parts.append(f"\n\n{table_md}\n\n")

                # Links
                elif tag_name == "a":
                    link_text = self._element_to_markdown(child).strip()
                    href = child.get("href", "").strip()
                    if link_text and href and not href.startswith("javascript:"):
                        parts.append(f"[{link_text}]({href})")
                    elif link_text:
                        parts.append(link_text)

                # Line breaks
                elif tag_name == "br":
                    parts.append("\n")

                # Strong / Bold / Em / Italic
                elif tag_name in ("strong", "b"):
                    strong_text = self._element_to_markdown(child).strip()
                    if strong_text:
                        parts.append(f" **{strong_text}** ")
                elif tag_name in ("em", "i"):
                    em_text = self._element_to_markdown(child).strip()
                    if em_text:
                        parts.append(f" *{em_text}* ")

                # Divs, sections, articles, and generic containers
                else:
                    inner = self._element_to_markdown(child)
                    parts.append(inner)

        return "".join(parts)

    def _list_to_markdown(self, list_tag: Tag, is_ordered: bool = False) -> str:
        """Convert ul/ol to clean Markdown list items."""
        items: List[str] = []
        counter = 1
        for li in list_tag.find_all("li", recursive=False):
            item_text = self._element_to_markdown(li).strip()
            # Clean embedded excessive newlines inside list item
            item_text = re.sub(r"\s*\n\s*", " ", item_text)
            if item_text:
                if is_ordered:
                    items.append(f"{counter}. {item_text}")
                    counter += 1
                else:
                    items.append(f"- {item_text}")
        return "\n".join(items)

    def _table_to_markdown(self, table_tag: Tag) -> str:
        """
        Convert table to standard Markdown table, preserving monetary amounts and headers.
        """
        rows: List[List[str]] = []

        for tr in table_tag.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            row_data = [
                re.sub(r"\s+", " ", self._element_to_markdown(c).strip()).replace("|", r"\|")
                for c in cells
            ]
            if any(row_data):
                rows.append(row_data)

        if not rows:
            return ""

        # Normalize column widths
        num_cols = max(len(r) for r in rows)
        if num_cols == 0:
            return ""

        padded_rows = [r + [""] * (num_cols - len(r)) for r in rows]

        # Use first row as header
        header = padded_rows[0]
        separator = ["---"] * num_cols

        md_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]

        for data_row in padded_rows[1:]:
            md_lines.append("| " + " | ".join(data_row) + " |")

        return "\n".join(md_lines)

    def _clean_whitespace_and_unicode(self, text: str) -> str:
        """
        Deterministic string cleaning:
        - NFKC normalization.
        - Zero-width space removal.
        - Non-breaking spaces converted to standard spaces.
        - Line-ending standardization to \\n.
        - Collapsing redundant spacing while maintaining paragraph breaks.
        """
        if not text:
            return ""

        # 1. Unicode normalization to NFKC
        text = unicodedata.normalize("NFKC", text)

        # 2. Replace non-breaking spaces and remove zero-width characters
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

        # 3. Standardize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 4. Clean trailing whitespace per line & collapse horizontal spacing
        cleaned_lines: List[str] = []
        for line in text.split("\n"):
            # Collapse multiple spaces/tabs into a single space, but preserve markdown table formatting
            if not line.strip().startswith("|"):
                line = re.sub(r"[ \t]+", " ", line)
            cleaned_lines.append(line.rstrip())

        text = "\n".join(cleaned_lines)

        # 5. Collapse 3+ consecutive newlines to 2 newlines (standard Markdown paragraph)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 6. Trim leading/trailing whitespace
        return text.strip()
