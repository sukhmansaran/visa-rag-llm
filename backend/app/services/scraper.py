"""
Web scraping service using Playwright for dynamic sites and pypdf for PDFs.
"""

import hashlib
import asyncio
from typing import Dict, Optional
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page
import pypdf
import httpx
from bs4 import BeautifulSoup
import html2text

from app.core.config import settings


class WebScraper:
    """Scrapes web content using Playwright and handles PDFs."""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
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
                # Default wait for network idle
                await page.wait_for_load_state("networkidle", timeout=10000)
            
            # Get page content
            raw_html = await page.content()
            title = await page.title()
            
            # Extract text content
            soup = BeautifulSoup(raw_html, 'html.parser')
            
            # Remove script, style, and nav elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()
            
            # Convert to markdown-ish text
            extracted_text = self.html_converter.handle(str(soup))
            
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
