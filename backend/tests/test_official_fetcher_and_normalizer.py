"""
Tests for AsyncOfficialFetcher and CanadaNormalizer (Stage B1 Foundation).

Covers all 20 required specifications:
1. Valid HTML response.
2. Plain-text response.
3. HTTP 304.
4. HTTP 403 and 404 (non-retryable client errors).
5. HTTP 429 with Retry-After.
6. Retryable server error (503) followed by success.
7. Exhausted retries (500).
8. Connect/read timeout.
9. Oversized streamed response.
10. Unsupported content type (e.g. application/pdf).
11. Invalid URL schemes and embedded credentials.
12. Redirect to a disallowed/SSRF address.
13. Malformed HTML normalization.
14. Navigation/footer/WET boilerplate removal.
15. Preservation of headings, tables, monetary amounts, dates, and legal references.
16. Empty or suspiciously short extraction.
17. Identical input producing identical normalized output and content hash.
18. Conditional request headers (If-None-Match, If-Modified-Since).
19. Client closure and resource cleanup.
20. Existing scraper compatibility.
"""

import pytest
import httpx

from app.services.official_fetcher import (
    AsyncOfficialFetcher,
    InvalidURLError,
    SSRFBlockedError,
    ResponseTooLargeError,
    UnsupportedContentTypeError,
    HTTPFetchError,
    RetryExhaustedError,
    FetchTimeoutError,
)
from app.services.canada_normalizer import (
    CanadaNormalizer,
    ContentTooShortError,
)


# Helper fixtures & deterministic mock sleep
class MockClock:
    def __init__(self):
        self.slept: list[float] = []

    async def sleep(self, seconds: float):
        self.slept.append(seconds)


@pytest.fixture
def mock_clock():
    return MockClock()


# 1. Valid HTML response
@pytest.mark.asyncio
async def test_valid_html_response(mock_clock):
    html_body = b"<!DOCTYPE html><html><head><title>Canada Study</title></head><body><main><h1>Study Permit</h1><p>Requirements for Canada.</p></main></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=html_body)

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/en/immigration/study.html")

    assert res.status_code == 200
    assert res.content_type.startswith("text/html")
    assert res.byte_count == len(html_body)
    assert "Study Permit" in res.text
    assert not res.is_not_modified
    assert len(mock_clock.slept) == 0


# 2. Plain-text response
@pytest.mark.asyncio
async def test_plain_text_response(mock_clock):
    text_body = b"IRCC Ministerial Instructions: Express Entry Draw #320. Minimum CRS: 524."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=text_body)

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/raw/notice.txt")

    assert res.status_code == 200
    assert res.content_type == "text/plain"
    assert "CRS: 524" in res.text
    assert res.byte_count == len(text_body)


# 3. HTTP 304 Not Modified
@pytest.mark.asyncio
async def test_http_304_not_modified(mock_clock):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("If-None-Match") == '"hash123"'
        return httpx.Response(304, headers={"ETag": '"hash123"'})

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/en/study.html", etag='"hash123"')

    assert res.status_code == 304
    assert res.is_not_modified is True
    assert res.byte_count == 0
    assert res.text == ""
    assert res.etag == '"hash123"'


# 4. HTTP 403 and 404 (non-retryable client errors)
@pytest.mark.asyncio
async def test_http_403_and_404_no_retries(mock_clock):
    attempts_404 = 0
    attempts_403 = 0

    def handler_404(request: httpx.Request) -> httpx.Response:
        nonlocal attempts_404
        attempts_404 += 1
        return httpx.Response(404, content=b"Page Not Found")

    def handler_403(request: httpx.Request) -> httpx.Response:
        nonlocal attempts_403
        attempts_403 += 1
        return httpx.Response(403, content=b"Forbidden Access")

    # 404 Test
    transport_404 = httpx.MockTransport(handler_404)
    async with AsyncOfficialFetcher(transport=transport_404, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        with pytest.raises(HTTPFetchError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/missing.html")
        assert exc_info.value.status_code == 404
        assert attempts_404 == 1  # Never retried

    # 403 Test
    transport_403 = httpx.MockTransport(handler_403)
    async with AsyncOfficialFetcher(transport=transport_403, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        with pytest.raises(HTTPFetchError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/restricted.html")
        assert exc_info.value.status_code == 403
        assert attempts_403 == 1  # Never retried

    assert len(mock_clock.slept) == 0


# 5. HTTP 429 with Retry-After
@pytest.mark.asyncio
async def test_http_429_with_retry_after(mock_clock):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "4"}, content=b"Rate limited")
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<main><p>Success after wait</p></main>")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/page.html")

    assert res.status_code == 200
    assert call_count == 2
    assert mock_clock.slept == [4.0]
    assert "Success after wait" in res.text


# 6. Retryable server error (503) followed by success
@pytest.mark.asyncio
async def test_retryable_server_error_followed_by_success(mock_clock):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, content=b"Service Temporarily Unavailable")
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<main><p>Now available</p></main>")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(
        transport=transport, backoff_factor=1.0, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0
    ) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/page.html")

    assert res.status_code == 200
    assert call_count == 2
    assert len(mock_clock.slept) == 1
    assert mock_clock.slept[0] == 1.0  # 1.0 * (2^0) + 0.0


# 7. Exhausted retries
@pytest.mark.asyncio
async def test_exhausted_retries(mock_clock):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, content=b"Internal Server Error")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(
        transport=transport, max_retries=2, backoff_factor=1.0, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0
    ) as fetcher:
        with pytest.raises(RetryExhaustedError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/failing.html")
        assert exc_info.value.status_code == 500
        assert calls == 3  # Initial + 2 retries
        assert len(mock_clock.slept) == 2


# 8. Connect/read timeout
@pytest.mark.asyncio
async def test_connect_read_timeout(mock_clock):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Socket read timed out")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(
        transport=transport, max_retries=1, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0
    ) as fetcher:
        with pytest.raises(FetchTimeoutError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/slow.html")
        assert "timed out" in str(exc_info.value)


# 9. Oversized streamed response
@pytest.mark.asyncio
async def test_oversized_streamed_response(mock_clock):
    large_payload = b"A" * 5000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=large_payload)

    transport = httpx.MockTransport(handler)
    # Configure limit of 1024 bytes
    async with AsyncOfficialFetcher(
        transport=transport, max_response_size=1024, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0
    ) as fetcher:
        with pytest.raises(ResponseTooLargeError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/huge.txt")
        assert "exceeded" in str(exc_info.value)


# 10. Unsupported content type
@pytest.mark.asyncio
async def test_unsupported_content_type(mock_clock):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.5...")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        with pytest.raises(UnsupportedContentTypeError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/guide.pdf")
        assert "Unsupported content type 'application/pdf'" in str(exc_info.value)


# 11. Invalid URL schemes and embedded credentials
@pytest.mark.asyncio
async def test_invalid_url_schemes_and_credentials():
    fetcher = AsyncOfficialFetcher()
    invalid_urls = [
        "ftp://ftp.canada.ca/files",
        "file:///etc/passwd",
        "http://admin:secret@www.canada.ca/login",
        "https://user@www.canada.ca/path",
        "javascript:alert(1)",
        "",
        "http://",
    ]
    for url in invalid_urls:
        with pytest.raises(InvalidURLError):
            await fetcher.fetch(url)


# 12. Redirect to a disallowed address (SSRF protection)
@pytest.mark.asyncio
async def test_redirect_to_disallowed_address(mock_clock):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://www.canada.ca/start":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})
        return httpx.Response(200, content=b"Secret Admin Data")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        with pytest.raises(SSRFBlockedError) as exc_info:
            await fetcher.fetch("https://www.canada.ca/start")
        assert "disallowed" in str(exc_info.value) or "private" in str(exc_info.value)


# 13. Malformed HTML normalization
def test_malformed_html_normalization():
    normalizer = CanadaNormalizer(min_char_count=20)
    broken_html = """
    <html>
        <head><title>Canada Visas</title>
        <body>
            <main>
                <h1>Broken Document
                <p>Paragraph missing closing tags with <b>bold text
                <div><span>Nested table without closing:
                <table><tr><td>Column 1<td>Column 2</table>
            </main>
    """
    res = normalizer.normalize_html(broken_html)
    assert res.title == "Canada Visas"
    assert "# Broken Document" in res.text
    assert "Column 1" in res.text
    assert len(res.content_hash) == 64


# 14. Navigation/footer/WET boilerplate removal
def test_boilerplate_removal():
    normalizer = CanadaNormalizer(min_char_count=20)
    page_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head><title>Eligibility - Canada.ca</title></head>
    <body>
        <header><nav class="breadcrumb" id="wb-bc">Home > Immigration</nav></header>
        <div id="wb-srch"><form><input type="search"></form></div>
        <main property="mainContentOfPage">
            <h1>Study Permit Eligibility</h1>
            <p>Applicants must be accepted by a designated learning institution.</p>
        </main>
        <div class="pagedetails"><a href="/report-problem">Report a problem</a></div>
        <footer class="gc-main-footer"><p>Terms and conditions</p></footer>
    </body>
    </html>
    """
    res = normalizer.normalize_html(page_html)
    assert "Study Permit Eligibility" in res.text
    assert "Home > Immigration" not in res.text
    assert "Report a problem" not in res.text
    assert "Terms and conditions" not in res.text
    assert res.title == "Eligibility"
    assert res.language == "en"


# 15. Preservation of headings, tables, monetary amounts, dates, and legal references
def test_preservation_of_statutory_and_legal_content():
    normalizer = CanadaNormalizer(min_char_count=20)
    statutory_html = """
    <html>
    <head><title>Proof of Funds - IRCC</title></head>
    <body>
        <main>
            <h1>Proof of Financial Support for Study Permits</h1>
            <p>As per Immigration and Refugee Protection Regulations (IRPR) s. 216(1), applicants must demonstrate sufficient financial funds.</p>
            <p>Effective January 1, 2024, the primary applicant must show a minimum of $20,635 CAD in unencumbered funds (75% of LICO).</p>
            <h2>Living Expense Thresholds</h2>
            <table>
                <thead>
                    <tr><th>Family Members</th><th>Required Amount (CAD)</th><th>Monthly Allowance</th></tr>
                </thead>
                <tbody>
                    <tr><td>1 (Single Applicant)</td><td>$20,635 CAD</td><td>$1,720 CAD</td></tr>
                    <tr><td>2 (Applicant + 1)</td><td>$25,690 CAD</td><td>$2,141 CAD</td></tr>
                </tbody>
            </table>
        </main>
    </body>
    </html>
    """
    res = normalizer.normalize_html(statutory_html)
    assert "# Proof of Financial Support for Study Permits" in res.text
    assert "s. 216(1)" in res.text
    assert "IRPR" in res.text
    assert "January 1, 2024" in res.text
    assert "$20,635 CAD" in res.text
    assert "$25,690 CAD" in res.text
    assert "## Living Expense Thresholds" in res.text
    # Verify table formatting
    assert "| Family Members | Required Amount (CAD) | Monthly Allowance |" in res.text
    assert "| --- | --- | --- |" in res.text
    assert "| 1 (Single Applicant) | $20,635 CAD | $1,720 CAD |" in res.text


# 16. Empty or suspiciously short extraction
def test_short_content_detection():
    strict_normalizer = CanadaNormalizer(min_char_count=50, strict=True)
    lenient_normalizer = CanadaNormalizer(min_char_count=50, strict=False)

    short_html = "<html><body><main><p>Page moved.</p></main></body></html>"

    # Strict raises ContentTooShortError
    with pytest.raises(ContentTooShortError):
        strict_normalizer.normalize_html(short_html)

    # Lenient logs warning and returns NormalizedDocument
    res = lenient_normalizer.normalize_html(short_html)
    assert len(res.warnings) > 0
    assert "suspiciously short" in res.warnings[0]


# 17. Identical input produces identical output and hash
def test_deterministic_normalization():
    normalizer = CanadaNormalizer()
    sample_html = """
    <html>
        <head><title>Express Entry</title><link rel="canonical" href="https://www.canada.ca/ee"></head>
        <body>
            <main>
                <h1>Express Entry Pool</h1>
                <p>Candidates are ranked using the Comprehensive Ranking System (CRS).</p>
                <ul>
                    <li>Age points</li>
                    <li>Education level</li>
                    <li>Official language benchmark (CLB 7+)</li>
                </ul>
            </main>
        </body>
    </html>
    """
    res1 = normalizer.normalize_html(sample_html)
    res2 = normalizer.normalize_html(sample_html)

    assert res1.text == res2.text
    assert res1.content_hash == res2.content_hash
    assert res1.canonical_url == "https://www.canada.ca/ee"
    assert res1.title == "Express Entry"


# 18. Conditional request headers sent
@pytest.mark.asyncio
async def test_conditional_request_headers_sent(mock_clock):
    received_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers["If-None-Match"] = request.headers.get("If-None-Match")
        received_headers["If-Modified-Since"] = request.headers.get("If-Modified-Since")
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<main><p>Content updated</p></main>")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        await fetcher.fetch(
            "https://www.canada.ca/page.html",
            etag='"alpha99"',
            last_modified="Sun, 08 Oct 2026 12:00:00 GMT",
        )

    assert received_headers["If-None-Match"] == '"alpha99"'
    assert received_headers["If-Modified-Since"] == "Sun, 08 Oct 2026 12:00:00 GMT"


# 19. Client closure and resource cleanup
@pytest.mark.asyncio
async def test_client_closure_and_resource_cleanup():
    fetcher = AsyncOfficialFetcher()
    client = await fetcher._get_client()
    assert not client.is_closed
    assert not fetcher._closed

    await fetcher.close()
    assert fetcher._closed
    assert client.is_closed

    with pytest.raises(RuntimeError):
        await fetcher._get_client()


# 20. Existing scraper and ingestion tests remain compatible
def test_existing_scraper_import_compatibility():
    from app.services.scraper import WebScraper, scrape_with_retry
    assert WebScraper is not None
    assert callable(scrape_with_retry)


# 21. Allowed domains policy enforcement
@pytest.mark.asyncio
async def test_allowed_domains_policy():
    fetcher = AsyncOfficialFetcher(allowed_domains={"canada.ca", "gc.ca"})

    # Legitimate subdomains allowed
    p1 = fetcher.validate_url("https://www.canada.ca/en/services.html")
    fetcher.check_allowed_domain(p1)

    p2 = fetcher.validate_url("https://cic.gc.ca/study")
    fetcher.check_allowed_domain(p2)

    # Substring / spoofed domains disallowed
    p3 = fetcher.validate_url("https://fakecanada.ca/phish")
    with pytest.raises(SSRFBlockedError):
        fetcher.check_allowed_domain(p3)

    p4 = fetcher.validate_url("https://external-host.org")
    with pytest.raises(SSRFBlockedError):
        fetcher.check_allowed_domain(p4)


# 22. Cloud metadata hostnames blocked
@pytest.mark.asyncio
async def test_cloud_metadata_blocked():
    fetcher = AsyncOfficialFetcher()
    for meta_url in [
        "http://metadata.google.internal/computeMetadata/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://instance-data/latest",
    ]:
        with pytest.raises(SSRFBlockedError):
            await fetcher.fetch(meta_url)


# 23. Cross-origin redirect strips sensitive headers
@pytest.mark.asyncio
async def test_cross_origin_redirect_strips_sensitive_headers(mock_clock):
    received_target_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "canada.ca" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://external-cdn.com/asset"})
        received_target_headers["authorization"] = request.headers.get("Authorization")
        received_target_headers["cookie"] = request.headers.get("Cookie")
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<main><p>Redirected Content</p></main>")

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch(
            "https://www.canada.ca/entry",
            extra_headers={"Authorization": "Bearer secret123", "Cookie": "session=abc"}
        )

    assert res.status_code == 200
    assert received_target_headers.get("authorization") is None
    assert received_target_headers.get("cookie") is None


# 24. UTF-8 preference for Canadian bilingual content (French accents preserved)
@pytest.mark.asyncio
async def test_utf8_preference_for_bilingual_french_content(mock_clock):
    french_text = "Ministère de l'Immigration, de la Francisation et de l'Intégration du Québec."
    french_bytes = french_text.encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        # Deliberately omit charset or let httpx default
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=french_bytes)

    transport = httpx.MockTransport(handler)
    async with AsyncOfficialFetcher(transport=transport, sleep_fn=mock_clock.sleep, random_fn=lambda: 0.0) as fetcher:
        res = await fetcher.fetch("https://www.canada.ca/fr/immigration.html")

    assert "Ministère" in res.text
    assert "Intégration" in res.text


# 25. Canonical URL validation
def test_canonical_url_validation():
    normalizer = CanadaNormalizer()

    # Valid canonical
    html_valid = '<html><head><link rel="canonical" href="https://www.canada.ca/en/study.html"><title>T</title></head><body><main><p>Content with enough length to meet default minimum character threshold.</p></main></body></html>'
    res_valid = normalizer.normalize_html(html_valid)
    assert res_valid.canonical_url == "https://www.canada.ca/en/study.html"

    # Relative canonical -> rejected to prevent identity confusion
    html_rel = '<html><head><link rel="canonical" href="/relative/path"><title>T</title></head><body><main><p>Content with enough length to meet default minimum character threshold.</p></main></body></html>'
    res_rel = normalizer.normalize_html(html_rel)
    assert res_rel.canonical_url is None

    # Invalid scheme / javascript -> rejected
    html_js = '<html><head><link rel="canonical" href="javascript:alert(1)"><title>T</title></head><body><main><p>Content with enough length to meet default minimum character threshold.</p></main></body></html>'
    res_js = normalizer.normalize_html(html_js)
    assert res_js.canonical_url is None


# 26. Table pipe escaping
def test_table_pipe_escaping():
    normalizer = CanadaNormalizer(min_char_count=20)
    table_html = """
    <html><body><main>
    <table>
        <tr><th>Option</th><th>Description</th></tr>
        <tr><td>Stream A</td><td>IRPR s. 216(1) | Study Permit Criteria</td></tr>
    </table>
    </main></body></html>
    """
    res = normalizer.normalize_html(table_html)
    assert r"IRPR s. 216(1) \| Study Permit Criteria" in res.text


# 27. Canada.ca dateModified metadata extraction
def test_canada_ca_date_modified_metadata():
    normalizer = CanadaNormalizer(min_char_count=20)
    html_with_date = """
    <html>
    <head><title>Page</title></head>
    <body>
        <main>
            <h1>Express Entry</h1>
            <p>Express Entry minimum Comprehensive Ranking System threshold details.</p>
            <div class="pagedetails">
                <dl id="wb-dtmd"><dt>Date modified:</dt><dd><time property="dateModified">2026-04-15</time></dd></dl>
            </div>
        </main>
    </body>
    </html>
    """
    res = normalizer.normalize_html(html_with_date)
    assert res.metadata.get("date_modified") == "2026-04-15"
    # Boilerplate wrapper itself removed from text
    assert "Date modified:" not in res.text


# 28. Large HTML anomaly detection warning
def test_extraction_anomaly_warning():
    normalizer = CanadaNormalizer(min_char_count=100, strict=False)
    # 6000 bytes of script/boilerplate that decomposes into very few chars
    heavy_boilerplate_html = "<html><body><script>" + ("console.log('padding');" * 300) + "</script><main><p>Tiny</p></main></body></html>"
    res = normalizer.normalize_html(heavy_boilerplate_html)
    assert any("extraction anomaly" in w for w in res.warnings)
