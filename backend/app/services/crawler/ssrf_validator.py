"""
SSRF Protection and IP Sandboxing for Crawler Pipeline.
Validates URLs against DNS rebinding, private networks (RFC1918), loopback,
cloud metadata endpoints (169.254.169.254), and enforces server-side domain allowlists.
"""

import socket
import ipaddress
from urllib.parse import urlparse
from typing import List, Optional, Set
import fnmatch
import logging

logger = logging.getLogger(__name__)

# Official Canadian immigration and provincial government domain allowlist
SERVER_ALLOWED_DOMAINS = [
    "canada.ca",
    "*.canada.ca",
    "cic.gc.ca",
    "*.cic.gc.ca",
    "gc.ca",
    "*.gc.ca",
    "ontario.ca",
    "*.ontario.ca",
    "quebec.ca",
    "*.quebec.ca",
    "alberta.ca",
    "*.alberta.ca",
    "gov.bc.ca",
    "*.gov.bc.ca",
    "saskatchewan.ca",
    "*.saskatchewan.ca",
    "manitoba.ca",
    "*.manitoba.ca",
    "novascotia.ca",
    "*.novascotia.ca",
    "princeedwardisland.ca",
    "*.princeedwardisland.ca",
    "gnb.ca",
    "*.gnb.ca",
    "gov.nl.ca",
    "*.gov.nl.ca",
    "welcomebc.ca",
    "*.welcomebc.ca",
    "immigratemanitoba.com",
    "*.immigratemanitoba.com",
    "educanada.ca",
    "*.educanada.ca",
    # Designated learning institutions referenced by the intent parser
    "utoronto.ca",
    "*.utoronto.ca",
    "mcgill.ca",
    "*.mcgill.ca",
    "ubc.ca",
    "*.ubc.ca",
    "uwaterloo.ca",
    "*.uwaterloo.ca",
    "ualberta.ca",
    "*.ualberta.ca",
    "umontreal.ca",
    "*.umontreal.ca",
    "queensu.ca",
    "*.queensu.ca",
    "dal.ca",
    "*.dal.ca",
    "uottawa.ca",
    "*.uottawa.ca",
    # No TLD-wide wildcards (*.ca, *.edu): anyone can register those, which would let
    # attacker-controlled pages into the knowledge base. Add vetted domains via
    # settings.CRAWLER_EXTRA_ALLOWED_DOMAINS instead.
]


def get_server_allowed_domains() -> List[str]:
    """Server-side allowlist: built-in official domains plus vetted extras from settings."""
    from app.core.config import settings
    extras = [d.strip().lower() for d in (settings.CRAWLER_EXTRA_ALLOWED_DOMAINS or []) if d.strip()]
    return SERVER_ALLOWED_DOMAINS + extras

# Blocked IP networks
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),       # Cloud metadata & link-local
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),       # Carrier-grade NAT
    ipaddress.ip_network("198.18.0.0/15"),       # Benchmark tests
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-Local
]


NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def is_ip_blocked(ip_addr: str) -> bool:
    """Check if an IP address belongs to private, loopback, or metadata ranges."""
    try:
        ip = ipaddress.ip_address(ip_addr)

        # Handle RFC 6052 Well-Known NAT64 Prefix (64:ff9b::/96)
        if ip.version == 6 and ip in NAT64_PREFIX:
            embedded_ipv4 = ipaddress.IPv4Address(ip.packed[-4:])
            return is_ip_blocked(str(embedded_ipv4))

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
        for net in BLOCKED_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return True


def is_domain_allowed(domain: str, allowed_patterns: Optional[List[str]] = None) -> bool:
    """
    Check if a domain matches approved patterns.
    If allowed_patterns is provided, domain must match both the server allowlist
    and allowed_patterns (defense-in-depth).
    """
    domain = domain.lower().strip()
    if not domain:
        return False

    # Block localhost and internal names directly
    if domain in ("localhost", "127.0.0.1", "::1", "metadata.google.internal") or domain.endswith(".local") or domain.endswith(".internal"):
        return False

    # Match server-side allowlist
    matches_server = any(fnmatch.fnmatch(domain, pattern) for pattern in get_server_allowed_domains())
    if not matches_server:
        return False

    # If caller provided custom patterns, enforce intersection
    if allowed_patterns:
        matches_custom = any(fnmatch.fnmatch(domain, pattern) for pattern in allowed_patterns)
        if not matches_custom:
            return False

    return True


def is_safe_url(url: str, allowed_patterns: Optional[List[str]] = None, resolve_dns: bool = True) -> bool:
    """
    Perform complete SSRF safety evaluation:
    1. Validates scheme (http/https).
    2. Validates hostname against server-side allowlist.
    3. If resolve_dns=True, resolves DNS and blocks loopback, private RFC1918, and cloud metadata IPs.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("SSRF blocked: Disallowed scheme '%s' in url: %s", parsed.scheme, url)
            return False

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False

        # Domain whitelist check
        if not is_domain_allowed(hostname, allowed_patterns):
            logger.warning("SSRF blocked: Domain '%s' not in allowed scope for url: %s", hostname, url)
            return False

        # Check if hostname itself is directly an IP literal
        try:
            direct_ip = ipaddress.ip_address(hostname)
            if is_ip_blocked(str(direct_ip)):
                logger.warning("SSRF blocked: Direct private/metadata IP '%s'", hostname)
                return False
        except ValueError:
            pass  # It's a hostname

        if not resolve_dns:
            return True

        # DNS resolution check
        try:
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                if is_ip_blocked(ip_str):
                    logger.warning("SSRF blocked: Host '%s' resolved to prohibited IP '%s'", hostname, ip_str)
                    return False
        except (socket.gaierror, socket.herror) as err:
            logger.warning("SSRF blocked: DNS resolution failed for '%s': %s", hostname, err)
            return False

        return True
    except Exception as exc:
        logger.error("SSRF validation error for %s: %s", url, exc)
        return False
