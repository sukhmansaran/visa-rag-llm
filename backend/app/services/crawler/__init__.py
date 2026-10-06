"""
Crawler Pipeline Service Package

A distributed, multi-stage crawling system targeting aggregator portals.
Replaces the single-URL WebScraper with a scalable pipeline that discovers links,
classifies pages, extracts content, and structures data using LLM.

Modules:
    types       - Data type definitions (FrontierEntry, FetchResult, etc.)
    frontier    - CrawlFrontier: Redis-backed URL priority queue
    robots      - RobotsChecker: robots.txt compliance
    throttle    - ThrottleManager: per-domain rate limiting
    worker      - CrawlerWorker: page fetching with retry and UA rotation
    classifier  - PageClassifier: keyword-based relevance classification
    extractor   - ContentExtractor: dual-engine text extraction
    structurer  - LLMStructurer: Gemini-based field structuring
    job_manager - CrawlJobManager: crawl job orchestration
    dedup       - Deduplicator: content hash deduplication
    cache       - ResponseCache: Redis-backed response caching
"""

# Imports added as modules are implemented:
from .frontier import CrawlFrontier
from .robots import RobotsChecker
from .throttle import ThrottleManager
from .worker import CrawlerWorker
from .classifier import PageClassifier
from .extractor import ContentExtractor
from .structurer import LLMStructurer
from .job_manager import CrawlJobManager
from .dedup import Deduplicator
from .cache import ResponseCache
