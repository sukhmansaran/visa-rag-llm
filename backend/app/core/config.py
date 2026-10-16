from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator, Field
import os
import re

TEST_ENVIRONMENTS = ("test", "testing", "pytest")
MIN_SECRET_KEY_LENGTH = 32
PLACEHOLDER_SECRET_MARKERS = ("your-secret-key", "change-in-production", "changeme", "replace-me")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "Overseas Visa Chatbot API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = Field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/visa_chatbot"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_AUTO_CREATE_TABLES: bool = False
    # NullPool: open a fresh connection per session. Used by the test suite, where every test runs on
    # its own event loop and pooled asyncpg connections can't be reused across loops.
    DATABASE_USE_NULL_POOL: bool = False
    SQL_ECHO: bool = False
    
    # Redis
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    
    # Ollama (local LLM and embeddings)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"  # pull with: ollama pull nomic-embed-text
    # Non-streaming calls must finish entirely within this (CPU inference ~7 tok/s -> 700 tokens ~100 s)
    OLLAMA_REQUEST_TIMEOUT_SECONDS: float = 180.0
    # Streaming calls: maximum gap between tokens (includes first-token latency / model load)
    OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS: float = 90.0
    # Model context window. Ollama's default can silently truncate the prompt (system + sources + history).
    OLLAMA_NUM_CTX: int = 4096
    # Ask thinking-capable models to skip hidden reasoning (a CPU can't afford it). Some builds ignore this.
    OLLAMA_THINK: bool = False

    # LLM gateway (M0.4). Per-role models; empty = OLLAMA_MODEL.
    LLM_MODEL_PLANNER: Optional[str] = None    # question analysis / decomposition
    LLM_MODEL_ANSWER: Optional[str] = None     # grounded answer writing
    LLM_MODEL_VERIFIER: Optional[str] = None   # claim checks against sources
    # Backup model (M0.4b): answers instead when the primary times out, errors (5xx/404) or replies empty.
    # At most one swap per request; empty = no failover.
    LLM_FALLBACK_MODEL: Optional[str] = None
    # Models run on CPU only (num_gpu=0). On a small GPU (MX330, 2 GB) Ollama evicts one model to fit another
    # into VRAM, costing ~30 s per primary<->monitor switch; keeping the monitor off the GPU lets both stay loaded.
    LLM_CPU_ONLY_MODELS: List[str] = []
    # A CPU serves one generation at a time well; extra calls wait in a queue (per process).
    LLM_MAX_CONCURRENT_CALLS: int = 1
    LLM_QUEUE_TIMEOUT_SECONDS: float = 300.0   # give up waiting for a free slot after this
    # Share the slots across processes via Redis (API + all workers use one Ollama). Off = per-process queue.
    LLM_GLOBAL_QUEUE: bool = True

    # Celery redelivery (M0.6a). A task whose worker died stays "unacked" in Redis; after this many seconds it is
    # put back on its queue. Must exceed the longest task (answer budget D3 = 5 min), or a task still running
    # would be delivered twice. On Windows (--pool=solo) kombu never restores by itself: see app/workers/maintenance.py.
    CELERY_VISIBILITY_TIMEOUT_SECONDS: int = 900

    # Answer jobs (M0.6b): long answers run as Celery jobs that publish progress events to Redis
    ANSWER_JOB_BUDGET_SECONDS: int = 300   # D3: 5 minutes per answer, then the job stops with error "time_budget"
    ANSWER_JOB_TTL_SECONDS: int = 3600     # job state and events expire from Redis after this
    SSE_HEARTBEAT_SECONDS: float = 15.0    # idle event streams send a heartbeat so proxies keep them open
    # A job nobody has picked up (no worker running): tell the user after this long, give up after the second
    JOB_QUEUED_WARN_SECONDS: float = 20.0
    JOB_QUEUED_GIVE_UP_SECONDS: float = 180.0

    # Request traces (M0.5): one PII-redacted record per chat request, deleted after the retention period (D7)
    TRACES_ENABLED: bool = True
    TRACE_RETENTION_DAYS: int = 30

    # RAG generation budget
    RAG_TOP_K: int = 4                    # chunks retrieved per question
    RAG_CONTEXT_CHARS: int = 4000         # max source text given to the model (~1,000 tokens)
    RAG_MAX_ANSWER_TOKENS: int = 450      # answer length cap (~7 tok/s on CPU -> ~1 min)
    RAG_TEMPERATURE: float = 0.0          # deterministic answers; >0 only adds run-to-run variation
    
    # Vector Database
    VECTOR_DB_TYPE: str = "chroma"  # chroma or pinecone
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_data"
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = ""
    PINECONE_INDEX_NAME: str = "visa-chatbot"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/2"
    
    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_REVIEW_PRICE_ID: str = ""
    
    # Firebase
    FIREBASE_STORAGE_BUCKET: str = ""
    FCM_SERVER_KEY: str = ""  # Firebase Cloud Messaging server key
    
    # Email (SMTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@pendu.app"
    FROM_NAME: str = "Pendu Visa Assistant"
    
    # Sentry
    SENTRY_DSN: str = ""
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8081",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]
    # Allow any localhost port via regex (development convenience only; never enable in production)
    CORS_ALLOW_LOCALHOST_REGEX: bool = False
    # Request rate limiting (disable only in test suites that exercise the app from one client)
    RATE_LIMIT_ENABLED: bool = True
    # Comma-separated proxy IPs whose X-Forwarded-For header is trusted for client IP resolution
    TRUSTED_PROXY_IPS: List[str] = []
    
    # Scraping
    MAX_CONCURRENT_SCRAPES: int = 5
    SCRAPE_TIMEOUT_SECONDS: int = 30
    USER_AGENT: str = "VisaChatbot/1.0"

    # Crawler Pipeline
    CRAWLER_MAX_CONCURRENT_WORKERS: int = 10
    CRAWLER_DEFAULT_MAX_DEPTH: int = 3
    CRAWLER_DEFAULT_MAX_PAGES: int = 10000
    CRAWLER_FRONTIER_TTL_DAYS: int = 7
    CRAWLER_RESPONSE_CACHE_TTL: int = 86400  # 24 hours in seconds
    # Vetted extra crawl domains (exact or "*.domain" patterns) on top of the built-in official allowlist
    CRAWLER_EXTRA_ALLOWED_DOMAINS: List[str] = []
    
    @validator("CORS_ORIGINS", "TRUSTED_PROXY_IPS", "CRAWLER_EXTRA_ALLOWED_DOMAINS", "LLM_CPU_ONLY_MODELS", pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @validator("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", pre=True)
    def prefer_ipv4_loopback_for_redis(cls, v):
        # On Windows "localhost" resolves to ::1 first. Redis/Memurai listen on 127.0.0.1 only, and the
        # async redis client then times out on ::1 instead of falling back, so rate limiting and token
        # revocation silently dropped to per-process memory. Use the IPv4 loopback explicitly.
        if isinstance(v, str):
            return re.sub(r"^(rediss?://(?:[^@/]*@)?)localhost(?=[:/]|$)", r"\g<1>127.0.0.1", v)
        return v

    @validator("SECRET_KEY", pre=True, always=True)
    def ensure_secret_key(cls, v, values):
        val = (v or "").strip()
        env = str(values.get("ENVIRONMENT", os.getenv("ENVIRONMENT", "development"))).lower()
        if env in TEST_ENVIRONMENTS:
            return val or "test-secret-key-32-chars-minimum-length-for-testing"
        if not val:
            raise ValueError("SECRET_KEY must be explicitly set outside test environments")
        if len(val) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters")
        if any(marker in val.lower() for marker in PLACEHOLDER_SECRET_MARKERS):
            raise ValueError(
                "SECRET_KEY is a placeholder value. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return val
    
    class Config:
        from pathlib import Path
        _backend_env = Path(__file__).resolve().parent.parent.parent / ".env"
        env_file = (str(_backend_env), ".env")
        case_sensitive = True
        extra = "ignore"


# Global settings instance
settings = Settings()
