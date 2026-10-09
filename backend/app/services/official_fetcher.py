"""
AsyncOfficialFetcher: Safe, robust HTTP/HTTPS client for official Canadian sources.

Enforces:
- Explicit connect, read, write, and pool timeouts.
- Response size limits enforced while streaming.
- Bounded retries with exponential backoff, jitter, and Retry-After support.
- Safe redirect following with SSRF prevention (blocking non-public IP targets).
- Conditional requests via ETag and Last-Modified (handling HTTP 304 Not Modified).
- Strict content-type validation (HTML and plain text only).
"""

import asyncio
import datetime
import ipaddress
import logging
import random
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


class FetcherError(Exception):
    """Base exception for all fetcher errors."""
    pass


class InvalidURLError(FetcherError):
    """Raised when the URL scheme is unsupported, malformed, or contains credentials."""
    pass


class SSRFBlockedError(FetcherError):
    """Raised when a request target or redirect attempts to reach a private or non-public address."""
    pass


class ResponseTooLargeError(FetcherError):
    """Raised when response body exceeds maximum allowed byte limit."""
    pass


class UnsupportedContentTypeError(FetcherError):
    """Raised when the response content type is not supported."""
    pass


class HTTPFetchError(FetcherError):
    """Raised on non-retryable HTTP errors or when retries are exhausted."""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}


class RetryExhaustedError(HTTPFetchError):
    """Raised when retry attempts have been exhausted."""
    pass


class FetchTimeoutError(FetcherError):
    """Raised when network connection or read times out after all retry attempts."""
    pass


@dataclass
class FetchResult:
    """Structured, immutable representation of a fetch operation."""
    requested_url: str
    final_url: str
    status_code: int
    headers: Dict[str, str]
    content_type: str
    byte_count: int
    fetched_at: datetime.datetime
    content: bytes
    text: str
    is_not_modified: bool = False
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    error_message: Optional[str] = None


class AsyncOfficialFetcher:
    """
    Asynchronous HTTP fetcher tailored for official public websites.

    Lifecycle:
        Use as an async context manager or call `.close()` explicitly:
            async with AsyncOfficialFetcher() as fetcher:
                result = await fetcher.fetch("https://www.canada.ca/...")
    """

    DEFAULT_USER_AGENT = (
        "PenduOfficialBot/1.0 (+https://pendu.app; official-canadian-immigration-pipeline)"
    )
    DEFAULT_MAX_RESPONSE_SIZE = 15 * 1024 * 1024  # 15 MiB
    DEFAULT_ALLOWED_CONTENT_TYPES: Tuple[str, ...] = (
        "text/html",
        "application/xhtml+xml",
        "text/plain",
    )
    BLOCKED_HOSTNAMES: Set[str] = {
        "localhost",
        "localhost.localdomain",
        "0.0.0.0",
        "127.0.0.1",
        "::1",
        "metadata.google.internal",
        "instance-data",
        "169.254.169.254",
    }

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        write_timeout: float = 5.0,
        pool_timeout: float = 5.0,
        max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        max_wait: float = 30.0,
        max_retry_after: float = 60.0,
        max_redirects: int = 5,
        allowed_content_types: Tuple[str, ...] = DEFAULT_ALLOWED_CONTENT_TYPES,
        allow_private_ips: bool = False,
        allowed_domains: Optional[Set[str]] = None,
        robots_checker: Optional[Any] = None,
        throttle_manager: Optional[Any] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep_fn: Optional[Callable[[float], Coroutine[Any, Any, None]]] = None,
        random_fn: Optional[Callable[[], float]] = None,
    ):
        self.user_agent = user_agent
        self.timeout = httpx.Timeout(
            timeout=connect_timeout + read_timeout,
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout,
        )
        self.max_response_size = max_response_size
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_wait = max_wait
        self.max_retry_after = max_retry_after
        self.max_redirects = max_redirects
        self.allowed_content_types = allowed_content_types
        self.allow_private_ips = allow_private_ips
        self.allowed_domains = {d.lower().strip() for d in allowed_domains} if allowed_domains else None
        self.robots_checker = robots_checker
        self.throttle_manager = throttle_manager
        self._custom_transport = transport
        self._sleep_fn = sleep_fn or asyncio.sleep
        self._random_fn = random_fn or random.random

        self._client: Optional[httpx.AsyncClient] = None
        self._closed = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or initialize the underlying httpx.AsyncClient."""
        if self._closed:
            raise RuntimeError("AsyncOfficialFetcher has been closed.")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                transport=self._custom_transport,
                follow_redirects=False,  # Manual redirect validation for SSRF safety
                headers={"User-Agent": self.user_agent},
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying client and free connection pool resources."""
        self._closed = True
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncOfficialFetcher":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def validate_url(self, url: str) -> urllib.parse.SplitResult:
        """
        Validate URL syntax, scheme, and userinfo.

        Raises:
            InvalidURLError: If scheme is unsupported, URL is empty, or contains credentials.
        """
        if not url or not isinstance(url, str):
            raise InvalidURLError("URL must be a non-empty string.")

        try:
            parsed = urllib.parse.urlsplit(url.strip())
        except Exception as err:
            raise InvalidURLError(f"Malformed URL: {err}") from err

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise InvalidURLError(f"Unsupported URL scheme '{scheme}'. Only http and https are permitted.")

        if parsed.username or parsed.password:
            raise InvalidURLError("Embedded user credentials in URLs are disallowed.")

        if not parsed.hostname:
            raise InvalidURLError("URL must contain a valid host.")

        return parsed

    def check_ssrf_destination(self, parsed: urllib.parse.SplitResult) -> None:
        """
        Enforce SSRF safety by blocking private, loopback, link-local, and multicast IP targets.
        """
        if self.allow_private_ips:
            return

        hostname = (parsed.hostname or "").strip().lower()

        if (
            hostname in self.BLOCKED_HOSTNAMES
            or hostname.endswith(".localhost")
            or hostname.endswith(".local")
            or hostname.endswith(".internal")
        ):
            raise SSRFBlockedError(f"Access to blocked hostname '{hostname}' is disallowed.")

        # Check IP literal directly
        try:
            ip = ipaddress.ip_address(hostname)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise SSRFBlockedError(f"Target IP address '{ip}' is private, loopback, or reserved.")
        except ValueError:
            # Not an IP literal: hostname will be resolved by transport.
            pass

    def check_allowed_domain(self, parsed: urllib.parse.SplitResult) -> None:
        """
        Validate host against configured allowed domains policy.
        Uses explicit boundary check (exact host or subdomain of allowed host).
        """
        if not self.allowed_domains:
            return
        hostname = (parsed.hostname or "").strip().lower()
        is_allowed = any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in self.allowed_domains
        )
        if not is_allowed:
            raise SSRFBlockedError(
                f"Hostname '{hostname}' is not permitted by allowed domains policy."
            )

    def _is_supported_content_type(self, content_type_header: str) -> bool:
        """Check if Content-Type media-type matches allowed types."""
        if not content_type_header:
            return False
        media_type = content_type_header.split(";")[0].strip().lower()
        return any(media_type == allowed for allowed in self.allowed_content_types)

    def _parse_retry_after(self, retry_after_header: Optional[str]) -> Optional[float]:
        """Parse Retry-After header as either seconds or HTTP-date."""
        if not retry_after_header:
            return None
        raw = retry_after_header.strip()
        # Case 1: Integer seconds
        if raw.isdigit():
            return float(raw)
        # Case 2: HTTP date
        try:
            target_dt = datetime.datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S GMT").replace(
                tzinfo=datetime.timezone.utc
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = (target_dt - now).total_seconds()
            return max(0.0, delta)
        except Exception:
            return None

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with full jitter."""
        exponential = self.backoff_factor * (2.0 ** attempt)
        jitter = self._random_fn() * self.backoff_factor
        return min(self.max_wait, exponential + jitter)

    async def fetch(
        self,
        url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """
        Execute safe HTTP request with retries, conditional headers, and streaming limit enforcement.

        Args:
            url: Public HTTP/HTTPS target.
            etag: Optional cached ETag for If-None-Match.
            last_modified: Optional cached Last-Modified for If-Modified-Since.
            extra_headers: Optional additional request headers.

        Returns:
            FetchResult instance.
        """
        client = await self._get_client()

        # Build initial headers
        headers: Dict[str, str] = {
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if extra_headers:
            headers.update(extra_headers)

        current_url = url
        parsed_target = self.validate_url(current_url)
        self.check_ssrf_destination(parsed_target)
        self.check_allowed_domain(parsed_target)

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            redirect_count = 0
            current_url = url

            while True:
                parsed_step = self.validate_url(current_url)
                self.check_ssrf_destination(parsed_step)
                self.check_allowed_domain(parsed_step)

                try:
                    request = client.build_request("GET", current_url, headers=headers)
                    response = await client.send(request, stream=True)

                    status = response.status_code
                    resp_headers = {k.lower(): v for k, v in response.headers.items()}
                    fetched_at = datetime.datetime.now(datetime.timezone.utc)

                    # 1. Handle Redirects (301, 302, 303, 307, 308)
                    if status in (301, 302, 303, 307, 308):
                        await response.aclose()
                        location = resp_headers.get("location")
                        if not location:
                            raise HTTPFetchError(
                                f"Redirect status {status} missing Location header",
                                status_code=status,
                                url=current_url,
                                headers=resp_headers,
                            )
                        redirect_count += 1
                        if redirect_count > self.max_redirects:
                            raise HTTPFetchError(
                                f"Max redirects ({self.max_redirects}) exceeded",
                                status_code=status,
                                url=current_url,
                                headers=resp_headers,
                            )
                        next_url = urllib.parse.urljoin(current_url, location)
                        parsed_next = self.validate_url(next_url)
                        self.check_ssrf_destination(parsed_next)
                        self.check_allowed_domain(parsed_next)

                        # Strip sensitive authentication headers on cross-origin redirect
                        if (parsed_next.netloc or "").lower() != (parsed_step.netloc or "").lower():
                            headers.pop("Authorization", None)
                            headers.pop("authorization", None)
                            headers.pop("Cookie", None)
                            headers.pop("cookie", None)

                        current_url = next_url
                        continue

                    # 2. Handle HTTP 304 Not Modified
                    if status == 304:
                        await response.aclose()
                        return FetchResult(
                            requested_url=url,
                            final_url=current_url,
                            status_code=304,
                            headers=resp_headers,
                            content_type=resp_headers.get("content-type", ""),
                            byte_count=0,
                            fetched_at=fetched_at,
                            content=b"",
                            text="",
                            is_not_modified=True,
                            etag=resp_headers.get("etag") or etag,
                            last_modified=resp_headers.get("last-modified") or last_modified,
                        )

                    # 3. Handle Permanent Client Errors (Do NOT retry)
                    if 400 <= status < 500 and status != 429:
                        body_snippet = await response.aread()
                        await response.aclose()
                        snippet_text = body_snippet[:200].decode("utf-8", errors="replace").strip()
                        raise HTTPFetchError(
                            f"HTTP client error {status}: {snippet_text}",
                            status_code=status,
                            url=current_url,
                            headers=resp_headers,
                        )

                    # 4. Handle 429 Rate Limit & Retryable Server Errors (500, 502, 503, 504)
                    if status == 429 or status in (500, 502, 503, 504):
                        await response.aclose()
                        if attempt < self.max_retries:
                            retry_after = self._parse_retry_after(resp_headers.get("retry-after"))
                            if retry_after is not None:
                                if retry_after > self.max_retry_after:
                                    raise HTTPFetchError(
                                        f"Retry-After {retry_after}s exceeds maximum allowed limit {self.max_retry_after}s",
                                        status_code=status,
                                        url=current_url,
                                        headers=resp_headers,
                                    )
                                wait_time = retry_after
                            else:
                                wait_time = self._calculate_backoff(attempt)

                            logger.warning(
                                f"Transient HTTP {status} on {current_url}. Retrying in {wait_time:.2f}s "
                                f"(attempt {attempt + 1}/{self.max_retries})"
                            )
                            await self._sleep_fn(wait_time)
                            break  # Break inner redirect loop to retry from original URL
                        else:
                            raise RetryExhaustedError(
                                f"HTTP {status} failed after {attempt + 1} attempts",
                                status_code=status,
                                url=current_url,
                                headers=resp_headers,
                            )

                    # 5. Handle Other Non-200 Responses
                    if not (200 <= status < 300):
                        await response.aclose()
                        raise HTTPFetchError(
                            f"Unexpected HTTP status {status}",
                            status_code=status,
                            url=current_url,
                            headers=resp_headers,
                        )

                    # 6. Validate Content-Type
                    content_type = resp_headers.get("content-type", "")
                    if not self._is_supported_content_type(content_type):
                        await response.aclose()
                        raise UnsupportedContentTypeError(
                            f"Unsupported content type '{content_type}' at {current_url}"
                        )

                    # 7. Stream Body with Strict Size Enforcement
                    chunks: List[bytes] = []
                    total_bytes = 0
                    try:
                        async for chunk in response.aiter_bytes():
                            total_bytes += len(chunk)
                            if total_bytes > self.max_response_size:
                                raise ResponseTooLargeError(
                                    f"Response size exceeded {self.max_response_size} bytes limit."
                                )
                            chunks.append(chunk)
                    finally:
                        await response.aclose()

                    content_bytes = b"".join(chunks)

                    # 8. Decode Text (prefer UTF-8, with fallback to response encoding or replacement)
                    try:
                        text_content = content_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        encoding = response.encoding or "utf-8"
                        try:
                            text_content = content_bytes.decode(encoding)
                        except Exception:
                            text_content = content_bytes.decode("utf-8", errors="replace")

                    return FetchResult(
                        requested_url=url,
                        final_url=current_url,
                        status_code=status,
                        headers=resp_headers,
                        content_type=content_type,
                        byte_count=len(content_bytes),
                        fetched_at=fetched_at,
                        content=content_bytes,
                        text=text_content,
                        is_not_modified=False,
                        etag=resp_headers.get("etag"),
                        last_modified=resp_headers.get("last-modified"),
                    )

                except (ResponseTooLargeError, UnsupportedContentTypeError, SSRFBlockedError, InvalidURLError):
                    raise
                except HTTPFetchError as http_err:
                    if http_err.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        last_exception = http_err
                        break  # Retry outer loop
                    raise
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as net_err:
                    last_exception = net_err
                    if attempt < self.max_retries:
                        wait_time = self._calculate_backoff(attempt)
                        logger.warning(
                            f"Network error on {current_url}: {net_err}. Retrying in {wait_time:.2f}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        await self._sleep_fn(wait_time)
                        break  # Retry outer loop
                    else:
                        if isinstance(net_err, httpx.TimeoutException):
                            raise FetchTimeoutError(
                                f"Request to {current_url} timed out after {attempt + 1} attempts"
                            ) from net_err
                        raise RetryExhaustedError(
                            f"Network failure on {current_url} after {attempt + 1} attempts: {net_err}"
                        ) from net_err

        if last_exception:
            raise last_exception
        raise FetcherError(f"Failed to fetch {url}")
