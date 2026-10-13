"""
Web scraping service using Playwright for dynamic sites and pypdf for PDFs.
"""

import hashlib
import asyncio
from typing import Dict, Optional
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
import pypdf
import httpx
from bs4 import BeautifulSoup
import html2text

from app.core.config import settings


# Page furniture that is never policy content (canada.ca uses these ids/classes; generic ones too)
_BOILERPLATE_SELECTORS = [
    "script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button",
    "#wb-dtmd", ".pagedetails", "#wb-info", ".gc-subway", "#wb-lng", ".wb-share", "[role=navigation]",
]


def extract_main_text(raw_html: str, converter: "html2text.HTML2Text") -> str:
    """
    Convert a page to clean text, keeping only its main content.

    Official pages wrap the policy text in <main>; menus, "Report a problem", share widgets and
    "Date modified" blocks would otherwise end up in every chunk and pollute retrieval.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    for selector in _BOILERPLATE_SELECTORS:
        for element in root.select(selector):
            element.decompose()
    text = converter.handle(str(root))
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


class WebScraper:
    """Scrapes web content using Playwright and handles PDFs."""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.html_converter = html2text.HTML2Text()
        # Keep link text, drop URLs: URLs are noise in embedded chunks
        self.html_converter.ignore_links = True
        self.html_converter.body_width = 0  # don't hard-wrap lines
        self.html_converter.ignore_images = True
        
    async def __aenter__(self):
        """Context manager entry - start browser."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close browser."""
        if self.browser:
            await self.browser.close()
    
    async def scrape_url(self, url: str, wait_for_selector: Optional[str] = None) -> Dict:
        """
        Scrape a URL and return structured content.
        
        Args:
            url: URL to scrape
            wait_for_selector: Optional CSS selector to wait for before scraping
            
        Returns:
            Dict with url, title, raw_html, extracted_text, content_hash, scraped_at
        """
        if url.lower().endswith('.pdf'):
            return await self._scrape_pdf(url)
        
        if not self.browser:
            raise RuntimeError("Browser not initialized. Use async context manager.")
        
        page = await self.browser.new_page()
        
        try:
            # Navigate with timeout
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.SCRAPE_TIMEOUT_SECONDS * 1000)
            
            # Wait for specific content if needed
            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=10000)
            else:
                # Best-effort wait for network idle. Sites with analytics/long-polling never go idle;
                # the DOM is already loaded, so a timeout here must not discard the page.
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    pass
            
            # Get page content
            raw_html = await page.content()
            title = await page.title()
            
            # Extract text content from the page's main content area only
            extracted_text = extract_main_text(raw_html, self.html_converter)
            
            # Clean up whitespace
            extracted_text = '\n'.join(line.strip() for line in extracted_text.split('\n') if line.strip())
            
            # Compute content hash
            content_hash = hashlib.sha256(extracted_text.encode()).hexdigest()
            
            return {
                'url': url,
                'title': title,
                'raw_html': raw_html,
                'extracted_text': extracted_text,
                'content_hash': content_hash,
                'scraped_at': datetime.utcnow().isoformat(),
            }
            
        finally:
            await page.close()
    
    async def _scrape_pdf(self, url: str) -> Dict:
        """
        Download and extract text from a PDF.
        
        Args:
            url: URL to PDF file
            
        Returns:
            Dict with url, title, extracted_text, content_hash, scraped_at
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=settings.SCRAPE_TIMEOUT_SECONDS)
            response.raise_for_status()
            pdf_content = response.content
        
        # Parse PDF
        with open('/tmp/temp.pdf', 'wb') as f:
            f.write(pdf_content)
        
        reader = pypdf.PdfReader('/tmp/temp.pdf')
        
        # Extract text from all pages
        extracted_text = ''
        for page in reader.pages:
            extracted_text += page.extract_text() + '\n\n'
        
        # Clean up
        extracted_text = extracted_text.strip()
        
        # Compute hash
        content_hash = hashlib.sha256(extracted_text.encode()).hexdigest()
        
        # Try to get title from metadata
        title = reader.metadata.title if reader.metadata and reader.metadata.title else url.split('/')[-1]
        
        return {
            'url': url,
            'title': title,
            'raw_html': None,  # PDFs don't have HTML
            'extracted_text': extracted_text,
            'content_hash': content_hash,
            'scraped_at': datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def respect_robots_txt(url: str) -> bool:
        """
        Check if scraping is allowed by robots.txt.
        
        TODO: Implement proper robots.txt parsing.
        For now, returns True (allowed).
        """
        # TODO: Use robotexclusionrulesparser or similar
        return True


async def scrape_with_retry(url: str, max_retries: int = 3) -> Dict:
    """
    Scrape a URL with automatic retries on failure.
    
    Args:
        url: URL to scrape
        max_retries: Maximum number of retry attempts
        
    Returns:
        Scraped content dict
    """
    for attempt in range(max_retries):
        try:
            async with WebScraper() as scraper:
                return await scraper.scrape_url(url)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            # Exponential backoff
            await asyncio.sleep(2 ** attempt)
    
    raise RuntimeError(f"Failed to scrape {url} after {max_retries} attempts")
