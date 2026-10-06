from typing import List
from pydantic_settings import BaseSettings
from pydantic import validator, Field
import os
import secrets


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "Overseas Visa Chatbot API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = Field(default_factory=lambda: os.getenv("SECRET_KEY") or secrets.token_urlsafe(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:1@localhost:5432/visa_chatbot"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Ollama (local LLM and embeddings)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"  # pull with: ollama pull nomic-embed-text
    
    # Vector Database
    VECTOR_DB_TYPE: str = "chroma"  # chroma or pinecone
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_data"
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = ""
    PINECONE_INDEX_NAME: str = "visa-chatbot"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
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
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8081"]
    
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
    
    @validator("CORS_ORIGINS", pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @validator("SECRET_KEY", pre=True, always=True)
    def ensure_secret_key(cls, v):
        if not v:
            raise ValueError("SECRET_KEY must be set in environment or generated")
        return v
    
    class Config:
        import os
        from pathlib import Path
        _backend_env = Path(__file__).resolve().parent.parent.parent / ".env"
        env_file = (str(_backend_env), ".env")
        case_sensitive = True


# Global settings instance
settings = Settings()
