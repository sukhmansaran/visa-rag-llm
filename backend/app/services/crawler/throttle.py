"""
ThrottleManager: Per-domain request rate limiter using Redis token buckets.

Implements per-domain rate limiting with Lua scripts for atomic token bucket
operations. Supports pausing domains (e.g., after HTTP 429) and permanently
blocking domains (e.g., after HTTP 403).

Default rates per tier:
    - Tier 1: 0.5 rps (1 request per 2 seconds)
    - Tier 2-5: 1.0 rps (1 request per second)
"""

import asyncio
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default throttle rates per tier
DEFAULT_TIER_RATES = {
    1: 0.5,   # 1 request per 2 seconds for Tier 1
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.0,
}

# Lua script for atomic token bucket acquire.
# Keys: [bucket_key, rate_key]
# Args: [current_time, default_rate]
# Returns: 1 if token acquired, 0 otherwise
TOKEN_BUCKET_LUA = """
local bucket_key = KEYS[1]
local rate_key = KEYS[2]
local now = tonumber(ARGV[1])
local default_rate = tonumber(ARGV[2])

-- Get configured rate or use default
local rate = tonumber(redis.call('GET', rate_key))
if not rate then
    rate = default_rate
end

-- Get current bucket state
local tokens = tonumber(redis.call('HGET', bucket_key, 'tokens'))
local last_refill = tonumber(redis.call('HGET', bucket_key, 'last_refill_time'))

if tokens == nil or last_refill == nil then
    -- Initialize bucket: start with 1 token (allow first request)
    tokens = 1.0
    last_refill = now
end

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local new_tokens = elapsed * rate
tokens = tokens + new_tokens

-- Cap tokens at max burst (equal to rate, minimum 1)
local max_tokens = math.max(rate, 1.0)
if tokens > max_tokens then
    tokens = max_tokens
end

-- Try to consume a token
if tokens >= 1.0 then
    tokens = tokens - 1.0
    redis.call('HSET', bucket_key, 'tokens', tostring(tokens))
    redis.call('HSET', bucket_key, 'last_refill_time', tostring(now))
    return 1
else
    -- Update refill time even when not consuming
    redis.call('HSET', bucket_key, 'last_refill_time', tostring(now))
    redis.call('HSET', bucket_key, 'tokens', tostring(tokens))
    return 0
end
"""


class ThrottleManager:
    """Per-domain request rate limiter using Redis token buckets."""

    def __init__(self, redis_client) -> None:
        """
        Initialize the ThrottleManager.

        Args:
            redis_client: A redis.asyncio.Redis client instance.
        """
        self.redis = redis_client

    async def acquire(self, domain: str) -> bool:
        """
        Try to acquire a token for the domain.

        Checks if the domain is blocked or paused before attempting
        to acquire a token from the token bucket.

        Args:
            domain: The domain to acquire a token for.

        Returns:
            True if a token was acquired, False otherwise.
        """
        # Check if domain is blocked
        blocked_key = f"throttle:{domain}:blocked"
        if await self.redis.exists(blocked_key):
            logger.debug("Domain %s is blocked, denying request", domain)
            return False

        # Check if domain is paused
        paused_key = f"throttle:{domain}:paused"
        if await self.redis.exists(paused_key):
            logger.debug("Domain %s is paused, denying request", domain)
            return False

        # Use Lua script for atomic token bucket operation
        bucket_key = f"throttle:{domain}:bucket"
        rate_key = f"throttle:{domain}:rate"
        now = time.time()
        default_rate = DEFAULT_TIER_RATES.get(2, 1.0)  # Default to 1.0 rps

        result = await self.redis.eval(
            TOKEN_BUCKET_LUA,
            2,
            bucket_key,
            rate_key,
            str(now),
            str(default_rate),
        )

        acquired = int(result) == 1
        if acquired:
            logger.debug("Token acquired for domain %s", domain)
        else:
            logger.debug("No token available for domain %s", domain)
        return acquired

    async def wait_and_acquire(self, domain: str) -> None:
        """
        Block until a token is available for the domain.

        Loops calling acquire() with asyncio.sleep(0.1) between attempts.
        Raises RuntimeError if the domain is blocked.

        Args:
            domain: The domain to acquire a token for.

        Raises:
            RuntimeError: If the domain is permanently blocked.
        """
        while True:
            # Check if domain is blocked before each attempt
            blocked_key = f"throttle:{domain}:blocked"
            if await self.redis.exists(blocked_key):
                raise RuntimeError(f"Domain {domain} is permanently blocked")

            if await self.acquire(domain):
                return

            await asyncio.sleep(0.1)

    async def set_rate(self, domain: str, requests_per_second: float) -> None:
        """
        Configure rate limit for a specific domain.

        Args:
            domain: The domain to configure.
            requests_per_second: The desired rate in requests per second.
        """
        rate_key = f"throttle:{domain}:rate"
        await self.redis.set(rate_key, str(requests_per_second))
        logger.info("Set rate for %s to %.2f rps", domain, requests_per_second)

    async def pause_domain(self, domain: str, duration_seconds: int) -> None:
        """
        Pause all requests to a domain for a specified duration.

        Used when a target site returns HTTP 429 (Too Many Requests).

        Args:
            domain: The domain to pause.
            duration_seconds: How long to pause in seconds.
        """
        paused_key = f"throttle:{domain}:paused"
        await self.redis.set(paused_key, "1", ex=duration_seconds)
        logger.warning(
            "Paused domain %s for %d seconds", domain, duration_seconds
        )

    async def block_domain(self, domain: str) -> None:
        """
        Permanently block a domain.

        Used when a target site returns HTTP 403 (Forbidden).

        Args:
            domain: The domain to block.
        """
        blocked_key = f"throttle:{domain}:blocked"
        await self.redis.set(blocked_key, "1")
        logger.warning("Permanently blocked domain %s", domain)
