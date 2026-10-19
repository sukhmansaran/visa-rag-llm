"""
CrawlerWorker: Fetches web pages with retry, UA rotation, and proxy support.

Uses httpx for static pages and Playwright for JavaScript-heavy pages.
Implements exponential backoff retry logic, user-agent rotation,
optional proxy rotation, and HTTP 403/429 handling.
"""

import asyncio
import io
import logging
import time
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx

from app.services.crawler.types import FetchResult
from app.services.crawler.throttle import ThrottleManager
from app.services.crawler.ssrf_validator import is_safe_url
from app.services.crawler.safe_http import BROWSER_ARGS, pin_browser_page, pinned_transport

logger = logging.getLogger(__name__)

# Pool of realistic browser User-Agent strings
_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Retry and redirect configuration
MAX_RETRIES = 3
BACKOFF_DELAYS = [2, 4, 8]  # seconds
MAX_REDIRECT_HOPS = 5


class CrawlerWorker:
    """Fetches web pages with retry, UA rotation, SSRF protection, and proxy support."""

    def __init__(
        self,
        throttle_manager: ThrottleManager,
        proxy_pool: Optional[list[str]] = None,
        allowed_domains: Optional[list[str]] = None,
        enforce_ssrf: bool = True,
    ) -> None:
        """
        Initialize the CrawlerWorker.

        Args:
            throttle_manager: ThrottleManager instance for rate limiting.
            proxy_pool: Optional list of proxy URLs for rotation.
            allowed_domains: Optional list of approved domain patterns.
            enforce_ssrf: If True, validate all URLs and redirects against SSRF policy.
        """
        self.throttle_manager = throttle_manager
        self.proxy_pool = proxy_pool
        self.allowed_domains = allowed_domains
        self.enforce_ssrf = enforce_ssrf
        self._user_agents = list(_DEFAULT_USER_AGENTS)
        self._ua_counter = 0
        self._proxy_counter = 0

    async def fetch(self, url: str, use_playwright: bool = False) -> FetchResult:
        """
        Fetch a URL with retry logic and user-agent rotation.

        Uses Playwright for JS-heavy pages, httpx for static pages.
        Retries up to 3 times with exponential backoff (2s, 4s, 8s).
        Handles HTTP 403 (block domain) and 429 (pause domain).
        Enforces SSRF validation before request and on each redirect hop.

        Args:
            url: The URL to fetch.
            use_playwright: If True, use Playwright for JS rendering.

        Returns:
            FetchResult with status, HTML, headers, and timing.

        Raises:
            ValueError: On SSRF security violation (blocked IP/domain).
            httpx.HTTPStatusError: On 403 after blocking the domain.
            RuntimeError: If all retries are exhausted.
        """
        if self.enforce_ssrf and not is_safe_url(url, self.allowed_domains):
            logger.warning("SSRF blocked: URL '%s' rejected by security policy", url)
            raise ValueError(f"SSRF blocked: URL '{url}' is not allowed or resolves to internal/prohibited IP")

        domain = urlparse(url).netloc
        last_exception: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                delay = BACKOFF_DELAYS[attempt - 1]
                logger.info(
                    "Retry %d/%d for %s after %ds delay",
                    attempt, MAX_RETRIES - 1, url, delay,
                )
                await asyncio.sleep(delay)

            user_agent = self._rotate_user_agent()
            proxy = self._get_proxy()
            start_time = time.monotonic()

            try:
                if use_playwright:
                    result = await self._fetch_playwright(url, user_agent, proxy)
                else:
                    result = await self._fetch_httpx(url, user_agent, proxy)

                fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
                status_code = result["status_code"]

                # Handle 403 - block domain and raise
                if status_code == 403:
                    await self.throttle_manager.block_domain(domain)
                    logger.warning("HTTP 403 from %s — domain blocked", domain)
                    raise httpx.HTTPStatusError(
                        f"HTTP 403 Forbidden from {url}",
                        request=httpx.Request("GET", url),
                        response=httpx.Response(403),
                    )

                # Handle 429 - pause domain and retry
                if status_code == 429:
                    retry_after = _parse_retry_after(result.get("headers", {}))
                    await self.throttle_manager.pause_domain(domain, retry_after)
                    logger.warning(
                        "HTTP 429 from %s — domain paused for %ds",
                        domain, retry_after,
                    )
                    last_exception = httpx.HTTPStatusError(
                        f"HTTP 429 Too Many Requests from {url}",
                        request=httpx.Request("GET", url),
                        response=httpx.Response(429),
                    )
                    continue

                # Handle other 4xx/5xx errors - retry
                if status_code >= 400:
                    last_exception = httpx.HTTPStatusError(
                        f"HTTP {status_code} from {url}",
                        request=httpx.Request("GET", url),
                        response=httpx.Response(status_code),
                    )
                    continue

                return FetchResult(
                    url=url,
                    status_code=status_code,
                    raw_html=result.get("html"),
                    extracted_text=None,
                    headers=result.get("headers", {}),
                    fetch_duration_ms=fetch_duration_ms,
                    used_playwright=use_playwright,
                )

            except ValueError:
                # SSRF or validation rejection - fail immediately without retry
                raise
            except httpx.HTTPStatusError:
                raise
            except Exception as exc:
                fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
                last_exception = exc
                logger.warning(
                    "Fetch attempt %d failed for %s: %s",
                    attempt + 1, url, exc,
                )
                continue

        # All retries exhausted
        logger.error("All %d retries exhausted for %s", MAX_RETRIES, url)
        raise RuntimeError(
            f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_exception}"
        )

    async def fetch_pdf(self, url: str) -> FetchResult:
        """
        Download a PDF and extract text using pypdf with SSRF validation.

        Args:
            url: The URL of the PDF to download.

        Returns:
            FetchResult with extracted_text set to the PDF text content.
        """
        if self.enforce_ssrf and not is_safe_url(url, self.allowed_domains):
            raise ValueError(f"SSRF blocked: URL '{url}' is not allowed or resolves to internal/prohibited IP")

        from pypdf import PdfReader

        user_agent = self._rotate_user_agent()
        proxy = self._get_proxy()
        start_time = time.monotonic()

        current_url = url
        redirect_hops = 0

        async with self._http_client(proxy) as client:
            while True:
                if self.enforce_ssrf and not is_safe_url(current_url, self.allowed_domains):
                    raise ValueError(f"SSRF blocked redirect target: {current_url}")

                response = await client.get(
                    current_url, headers={"User-Agent": user_agent}
                )

                if response.is_redirect:
                    redirect_hops += 1
                    if redirect_hops > MAX_REDIRECT_HOPS:
                        raise httpx.TooManyRedirects(
                            f"Exceeded max redirects ({MAX_REDIRECT_HOPS}) for {url}",
                            request=response.request,
                        )

                    location = response.headers.get("location")
                    if not location:
                        break

                    next_url = urljoin(str(response.url), location)
                    if self.enforce_ssrf and not is_safe_url(next_url, self.allowed_domains):
                        logger.warning("SSRF blocked redirect from %s to %s", current_url, next_url)
                        raise ValueError(f"SSRF blocked redirect target: {next_url}")

                    current_url = next_url
                else:
                    break

            response.raise_for_status()

        fetch_duration_ms = int((time.monotonic() - start_time) * 1000)

        # Extract text from PDF bytes
        pdf_reader = PdfReader(io.BytesIO(response.content))
        text_parts = []
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        extracted_text = "\n".join(text_parts)

        return FetchResult(
            url=url,
            status_code=response.status_code,
            raw_html=None,
            extracted_text=extracted_text,
            headers=dict(response.headers),
            fetch_duration_ms=fetch_duration_ms,
            used_playwright=False,
        )

    def _http_client(self, proxy: Optional[str]) -> httpx.AsyncClient:
        """
        Redirects are followed by hand so each hop is checked. Connections are DNS-pinned (M0.9): the
        address that passed the SSRF check is the one connected to. Through a proxy the proxy resolves
        the host, so pinning cannot apply there.
        """
        pin = self.enforce_ssrf and not proxy
        return httpx.AsyncClient(timeout=30.0, proxy=proxy, follow_redirects=False,
                                 transport=pinned_transport() if pin else None)

    def _rotate_user_agent(self) -> str:
        """
        Round-robin through the user-agent pool.

        Returns:
            The next user-agent string.
        """
        ua = self._user_agents[self._ua_counter % len(self._user_agents)]
        self._ua_counter += 1
        return ua

    def _get_proxy(self) -> Optional[str]:
        """
        Round-robin through the proxy pool, if configured.

        Returns:
            The next proxy URL, or None if no proxy pool.
        """
        if not self.proxy_pool:
            return None
        proxy = self.proxy_pool[self._proxy_counter % len(self.proxy_pool)]
        self._proxy_counter += 1
        return proxy

    async def _fetch_httpx(
        self, url: str, user_agent: str, proxy: Optional[str]
    ) -> dict:
        """Fetch a URL using httpx.AsyncClient with manual redirect SSRF validation."""
        current_url = url
        redirect_hops = 0

        async with self._http_client(proxy) as client:
            while True:
                if self.enforce_ssrf and not is_safe_url(current_url, self.allowed_domains):
                    raise ValueError(f"SSRF blocked redirect target: {current_url}")

                response = await client.get(
                    current_url, headers={"User-Agent": user_agent}
                )

                if response.is_redirect:
                    redirect_hops += 1
                    if redirect_hops > MAX_REDIRECT_HOPS:
                        raise httpx.TooManyRedirects(
                            f"Exceeded max redirects ({MAX_REDIRECT_HOPS}) for {url}",
                            request=response.request,
                        )

                    location = response.headers.get("location")
                    if not location:
                        break

                    next_url = urljoin(str(response.url), location)
                    if self.enforce_ssrf and not is_safe_url(next_url, self.allowed_domains):
                        logger.warning("SSRF blocked redirect from %s to %s", current_url, next_url)
                        raise ValueError(f"SSRF blocked redirect target: {next_url}")

                    current_url = next_url
                else:
                    break

        return {
            "status_code": response.status_code,
            "html": response.text,
            "headers": dict(response.headers),
        }

    async def _fetch_playwright(
        self, url: str, user_agent: str, proxy: Optional[str]
    ) -> dict:
        """Fetch a URL using Playwright (chromium) for JS rendering with route sandboxing."""
        if self.enforce_ssrf and not is_safe_url(url, self.allowed_domains):
            raise ValueError(f"SSRF blocked: URL '{url}' is not allowed or resolves to internal/prohibited IP")

        from playwright.async_api import async_playwright

        proxy_config = {"server": proxy} if proxy else None

        async with async_playwright() as p:
            # With SSRF enforced, Chromium cannot resolve names: every request is served through a
            # DNS-pinned client (M0.9), and only to allowed domains
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS if self.enforce_ssrf else None)
            context = await browser.new_context(
                user_agent=user_agent,
                proxy=None if self.enforce_ssrf else proxy_config,
            )
            page = await context.new_page()
            client = self._http_client(proxy)

            if self.enforce_ssrf:
                await pin_browser_page(
                    page, client, lambda req_url: is_safe_url(req_url, self.allowed_domains, resolve_dns=False, quiet=True))

            try:
                response = await page.goto(url, wait_until="networkidle", timeout=30000)
                html = await page.content()
                status_code = response.status if response else 200
                headers = dict(response.headers) if response else {}
            finally:
                await context.close()
                await browser.close()
                await client.aclose()

        return {
            "status_code": status_code,
            "html": html,
            "headers": headers,
        }


def _parse_retry_after(headers: dict) -> int:
    """
    Parse the Retry-After header value.

    Returns the number of seconds to wait, defaulting to 120
    if the header is missing or unparseable.
    """
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after is not None:
        try:
            return int(retry_after)
        except (ValueError, TypeError):
            pass
    return 120
