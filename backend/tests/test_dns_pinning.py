"""
DNS pinning for external fetches (M0.9): the address that passed the SSRF check is the one connected to.

The attack: a hostile DNS server answers the check with a public address and the connection with a private
one (DNS rebinding). Before M0.9 the crawler resolved twice (is_safe_url, then httpx), so this got through.
"""

import socket
from collections import defaultdict
from typing import Dict, List

import httpcore
import httpx
import pytest

from app.services.crawler import safe_http
from app.services.crawler.safe_http import (BROWSER_ARGS, BlockedDestinationError, pin_browser_page,
                                            pinned_client, pinned_transport)
from app.services.crawler.worker import CrawlerWorker

PUBLIC = "205.193.215.159"
PUBLIC_2 = "205.193.215.160"


class FakeStream(httpcore.AsyncNetworkStream):
    """Serves one canned HTTP/1.1 response."""

    def __init__(self, response: bytes):
        self._response = response

    async def read(self, max_bytes, timeout=None):
        data, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return data

    async def write(self, buffer, timeout=None):
        pass

    async def aclose(self):
        pass

    def get_extra_info(self, info):
        return None


class RecordingBackend(httpcore.AsyncNetworkBackend):
    """Stands in for the real socket layer: records where connections go."""

    def __init__(self, responses: Dict[str, bytes] = None):
        self.connected: List[str] = []
        self.responses = responses or {}

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        if host in self.responses:
            return FakeStream(self.responses[host])
        raise httpcore.ConnectError(f"test: no server at {host}")

    async def sleep(self, seconds):
        pass


def rebinding_dns(monkeypatch, answers: Dict[str, List[str]]) -> Dict[str, int]:
    """socket.getaddrinfo answering each host's lookups in turn (last answer repeats)."""
    calls: Dict[str, int] = defaultdict(int)

    def fake_getaddrinfo(host, port, *args, **kwargs):
        sequence = answers[host]
        ip = sequence[min(calls[host], len(sequence) - 1)]
        calls[host] += 1
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return calls


def ok_response(body: bytes = b"ok") -> bytes:
    return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)


# ---------------------------------------------------------------- the rebinding attack

@pytest.mark.asyncio
async def test_rebinding_between_check_and_connect_is_blocked(monkeypatch):
    """The M0.9 'done when': first resolution public, second private → blocked, nothing connects."""
    calls = rebinding_dns(monkeypatch, {"www.canada.ca": [PUBLIC, "127.0.0.1"]})
    sockets = RecordingBackend()
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", sockets.connect_tcp)

    worker = CrawlerWorker.__new__(CrawlerWorker)
    worker.enforce_ssrf, worker.allowed_domains = True, None
    with pytest.raises(BlockedDestinationError):
        await worker._fetch_httpx("http://www.canada.ca/en.html", "test-agent", proxy=None)
    assert calls["www.canada.ca"] == 2  # is_safe_url's check, then the pinned connection's own lookup
    assert sockets.connected == []  # never reached 127.0.0.1


@pytest.mark.asyncio
async def test_rebinding_on_a_redirect_hop_is_blocked(monkeypatch):
    # evil.canada.ca passes both of the worker's redirect checks, then rebinds for the connection
    rebinding_dns(monkeypatch, {"www.canada.ca": [PUBLIC], "evil.canada.ca": [PUBLIC_2, PUBLIC_2, "169.254.169.254"]})
    sockets = RecordingBackend({PUBLIC: b"HTTP/1.1 302 Found\r\nLocation: http://evil.canada.ca/latest/meta-data\r\n"
                                        b"Content-Length: 0\r\n\r\n"})
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", sockets.connect_tcp)

    worker = CrawlerWorker.__new__(CrawlerWorker)
    worker.enforce_ssrf, worker.allowed_domains = True, None
    with pytest.raises(BlockedDestinationError):
        await worker._fetch_httpx("http://www.canada.ca/en.html", "test-agent", proxy=None)
    assert sockets.connected == [PUBLIC]  # the metadata address was never connected to


# ---------------------------------------------------------------- the pinned backend

@pytest.mark.asyncio
async def test_connects_to_exactly_the_address_it_checked():
    lookups = []

    async def resolver(host, port):
        lookups.append(host)
        return [PUBLIC]

    sockets = RecordingBackend({PUBLIC: ok_response()})
    async with httpx.AsyncClient(transport=pinned_transport(resolver, sockets)) as client:
        response = await client.get("http://www.canada.ca/en.html")
    assert response.text == "ok"
    assert lookups == ["www.canada.ca"] and sockets.connected == [PUBLIC]
    assert response.request.headers["host"] == "www.canada.ca"  # the server still sees its own name


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"], ["fd00::1"],
    [PUBLIC, "192.168.1.1"],  # one bad record poisons the set
    ["64:ff9b::7f00:1"],  # NAT64-wrapped 127.0.0.1
])
async def test_prohibited_addresses_are_refused(addresses):
    async def resolver(host, port):
        return addresses

    sockets = RecordingBackend()
    async with httpx.AsyncClient(transport=pinned_transport(resolver, sockets)) as client:
        with pytest.raises(BlockedDestinationError):
            await client.get("http://www.canada.ca/")
    assert sockets.connected == []


@pytest.mark.asyncio
async def test_ip_literal_urls_are_checked_too():
    sockets = RecordingBackend()
    async with httpx.AsyncClient(transport=pinned_transport(inner=sockets)) as client:
        with pytest.raises(BlockedDestinationError):
            await client.get("http://127.0.0.1:8000/admin")
    assert sockets.connected == []


@pytest.mark.asyncio
async def test_falls_through_to_the_next_checked_address():
    async def resolver(host, port):
        return [PUBLIC, PUBLIC_2]

    sockets = RecordingBackend({PUBLIC_2: ok_response()})  # the first address is down
    async with httpx.AsyncClient(transport=pinned_transport(resolver, sockets)) as client:
        assert (await client.get("http://www.canada.ca/")).text == "ok"
    assert sockets.connected == [PUBLIC, PUBLIC_2]


@pytest.mark.asyncio
async def test_dns_failure_is_a_connect_error_not_a_crash():
    async def resolver(host, port):
        raise socket.gaierror(11001, "getaddrinfo failed")

    async with httpx.AsyncClient(transport=pinned_transport(resolver, RecordingBackend())) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("http://nonexistent.canada.ca/")


def test_pinning_fails_loudly_if_httpx_internals_change(monkeypatch):
    class NoBackendPool:
        pass

    real_init = httpx.AsyncHTTPTransport.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self._pool = NoBackendPool()

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", init)
    with pytest.raises(RuntimeError, match="DNS pinning"):
        pinned_transport()


# ---------------------------------------------------------------- every fetch path is pinned

def test_crawler_and_shared_clients_use_the_pinned_transport():
    """Official fetcher: see the next test. Scraper and robots.txt use pinned_client."""
    worker = CrawlerWorker.__new__(CrawlerWorker)
    worker.enforce_ssrf = True
    assert isinstance(worker._http_client(None)._transport._pool._network_backend, safe_http.PinnedNetworkBackend)
    assert isinstance(pinned_client()._transport._pool._network_backend, safe_http.PinnedNetworkBackend)


# ---------------------------------------------------------------- the browser

def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")
async def test_browser_requests_all_go_through_the_pinned_client():
    """
    Real Chromium: pages, redirects and sub-resources are served by our client; Chromium resolves nothing.
    Redirects are followed by the handler (Chromium re-fetches a fulfilled navigation 3xx from the network).
    """
    from playwright.async_api import async_playwright

    seen = []

    def site(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://www.canada.ca/new"})
        if request.url.path == "/escape":
            return httpx.Response(302, headers={"location": "https://evil.example.com/"})
        if request.url.path == "/new":
            html = ('<html><body><main>Study permit page</main>'
                    '<img src="https://evil.example.com/x.png">'
                    '<img src="https://www.canada.ca/logo.png"></body></html>')
            return httpx.Response(200, html=html)
        return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(site))
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        page = await browser.new_page()
        await pin_browser_page(page, client, lambda url: ".canada.ca/" in url)
        response = await page.goto("https://www.canada.ca/old", wait_until="networkidle")
        content = await page.content()
        escape_error = None
        try:
            await page.goto("https://www.canada.ca/escape", timeout=15000)
        except Exception as err:  # a redirect off the allowlist is refused, not followed
            escape_error = str(err)
        await browser.close()
    await client.aclose()

    assert response.status == 200 and "Study permit page" in content
    assert seen == ["https://www.canada.ca/old", "https://www.canada.ca/new", "https://www.canada.ca/logo.png",
                    "https://www.canada.ca/escape"]  # evil.example.com never requested
    assert escape_error and "ERR_BLOCKED_BY_CLIENT" in escape_error


@pytest.mark.asyncio
@pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")
async def test_browser_without_the_route_cannot_reach_anything():
    """BROWSER_ARGS alone: Chromium's own resolver is off, so an unrouted request fails."""
    from playwright.async_api import Error as PlaywrightError, async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        page = await browser.new_page()
        with pytest.raises(PlaywrightError, match="ERR_NAME_NOT_RESOLVED"):
            await page.goto("https://www.canada.ca/", timeout=15000)
        await browser.close()


# ---------------------------------------------------------------- live

def _online() -> bool:
    try:
        socket.getaddrinfo("www.canada.ca", 443)
        return True
    except OSError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _online(), reason="no network")
async def test_live_https_still_validates_certificates():
    """SNI and certificate checks use the host name, not the pinned IP."""
    async with pinned_client(timeout=20) as client:
        response = await client.get("https://www.canada.ca/en/immigration-refugees-citizenship.html")
    assert response.status_code == 200 and "Immigration" in response.text


def test_quiet_checks_log_at_debug_not_warning(caplog):
    """Blocked third-party extras (analytics, fonts) appear on every canada.ca page: not worth a warning each."""
    from app.services.crawler.ssrf_validator import is_safe_url

    with caplog.at_level("DEBUG", logger="app.services.crawler.ssrf_validator"):
        assert not is_safe_url("https://fonts.gstatic.com/s/lato.woff2", resolve_dns=False, quiet=True)
        assert not is_safe_url("https://evil.example.com/", resolve_dns=False)
    levels = [(r.levelname, "gstatic" in r.getMessage()) for r in caplog.records]
    assert levels == [("DEBUG", True), ("WARNING", False)]
