"""
DNS-pinned HTTP for every fetch of an external page (M0.9).

`is_safe_url()` resolves a host and checks the addresses, but httpx (or Chromium) then resolves the host
*again* to connect. A hostile DNS server can answer the check with a public address and the connection
with a private one (DNS rebinding), reaching 127.0.0.1, the LAN or 169.254.169.254.

Here the check and the connection use the same lookup: `PinnedNetworkBackend` sits under httpx, resolves
each host once per connection, refuses if any address is prohibited, and connects to one of exactly those
addresses. TLS still uses the original host name (SNI and certificate checks are unchanged) and the Host
header is untouched. Every redirect hop opens its own connection, so every hop is checked.

Chromium resolves names itself, so `pin_browser_page()` disables its resolver (`BROWSER_ARGS`) and serves
every request the page makes through a pinned httpx client instead.
"""

import asyncio
import logging
import socket
from typing import Awaitable, Callable, Iterable, List, Optional
from urllib.parse import urljoin

import httpcore
import httpx

from app.services.crawler.ssrf_validator import is_ip_blocked

logger = logging.getLogger(__name__)

DNS_TIMEOUT_SECONDS = 10.0

# Chromium may not resolve any name itself: every request must come through pin_browser_page's route
BROWSER_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND"]

Resolver = Callable[[str, int], Awaitable[List[str]]]


class BlockedDestinationError(ValueError):
    """A host resolved to a prohibited address. A ValueError, so callers treat it as a security rejection."""


async def system_resolve(host: str, port: int) -> List[str]:
    """All addresses for host, in the system's preferred order, without duplicates."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, check every address, connect only to a checked address."""

    def __init__(self, resolver: Optional[Resolver] = None, inner: Optional[httpcore.AsyncNetworkBackend] = None):
        self._resolve = resolver or system_resolve
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: Optional[float] = None,
                          local_address: Optional[str] = None, socket_options: Optional[Iterable] = None,
                          ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await asyncio.wait_for(self._resolve(host, port), timeout or DNS_TIMEOUT_SECONDS)
        except (OSError, asyncio.TimeoutError) as err:
            raise httpcore.ConnectError(f"DNS resolution failed for {host}: {err}") from err
        if not addresses:
            raise httpcore.ConnectError(f"DNS resolution returned no addresses for {host}")
        blocked = [ip for ip in addresses if is_ip_blocked(ip)]
        if blocked:  # one bad address is enough: the record set is hostile or misconfigured
            logger.warning("SSRF blocked: %s resolved to prohibited address %s", host, blocked[0])
            raise BlockedDestinationError(f"SSRF blocked: {host} resolves to a prohibited address")

        last_error: Optional[Exception] = None
        for ip in addresses:
            try:
                return await self._inner.connect_tcp(ip, port, timeout=timeout, local_address=local_address,
                                                     socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as err:
                last_error = err
        raise last_error

    async def connect_unix_socket(self, path: str, timeout: Optional[float] = None,
                                  socket_options: Optional[Iterable] = None) -> httpcore.AsyncNetworkStream:
        raise BlockedDestinationError("SSRF blocked: unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def pinned_transport(resolver: Optional[Resolver] = None,
                     inner: Optional[httpcore.AsyncNetworkBackend] = None, **kwargs) -> httpx.AsyncHTTPTransport:
    """An httpx transport whose connections go through PinnedNetworkBackend."""
    transport = httpx.AsyncHTTPTransport(**kwargs)
    pool = transport._pool
    if not hasattr(pool, "_network_backend"):  # httpx/httpcore internals changed: fail loudly, never unpinned
        raise RuntimeError("httpcore connection pool has no _network_backend; DNS pinning cannot be applied")
    pool._network_backend = PinnedNetworkBackend(resolver, inner)
    return transport


def pinned_client(**kwargs) -> httpx.AsyncClient:
    """An httpx client for external pages. Redirects are not followed unless the caller asks."""
    kwargs.setdefault("follow_redirects", False)
    return httpx.AsyncClient(transport=pinned_transport(), **kwargs)


# Response headers Chromium must not see after httpx has already decoded the body
_HOP_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection", "keep-alive"}


MAX_BROWSER_REDIRECTS = 5


async def pin_browser_page(page, client: httpx.AsyncClient, is_allowed: Callable[[str], bool]) -> None:
    """
    Serve every request `page` makes through `client` (a pinned_client) after `is_allowed(url)`.
    The browser must be launched with BROWSER_ARGS so nothing can bypass the route.

    Redirects are followed here, each hop checked, and only the final response is given to the browser:
    Chromium does not honour a fulfilled 3xx on a navigation and re-requests the page from the network
    itself (seen live; with BROWSER_ARGS that fails closed instead). The page keeps its original URL.
    """
    async def handler(route):
        request = route.request
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        method, content = request.method, request.post_data_buffer
        try:
            for _ in range(MAX_BROWSER_REDIRECTS + 1):
                if not is_allowed(url):
                    logger.warning("SSRF blocked browser request to: %s", url)
                    await route.abort("blockedbyclient")
                    return
                response = await client.request(method, url, headers=request.headers, content=content)
                location = response.headers.get("location")
                if not (response.is_redirect and location):
                    break
                url = urljoin(str(response.url), location)
                if response.status_code in (301, 302, 303):
                    method, content = "GET", None
            else:
                await route.abort("failed")  # too many redirects
                return
        except BlockedDestinationError:
            await route.abort("blockedbyclient")
            return
        except httpx.HTTPError as err:
            logger.debug("Browser request failed for %s: %s", url, err)
            await route.abort("failed")
            return
        headers = {k: v for k, v in response.headers.items() if k.lower() not in _HOP_HEADERS}
        await route.fulfill(status=response.status_code, headers=headers, body=response.content)

    await page.route("**/*", handler)
