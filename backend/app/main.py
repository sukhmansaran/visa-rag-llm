from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging
from app.core.middleware import (
    RequestIDMiddleware,
    LoggingMiddleware,
    ErrorHandlerMiddleware,
    RateLimitMiddleware
)
from app.api.v1 import (
    auth, health, chat, ingest, profile, documents, 
    watchlist_api, notifications, payments, reviews, devices, files,
    tourist_visa, travel, travel_costs, travel_packages, tour_packages,
    applications, visa_risk, subscription, crawler
)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for startup and shutdown."""
    # Startup
    logger.info(f"Starting {settings.APP_NAME}...")
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database connections closed")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for overseas visa and university application guidance",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add custom middleware (order matters!)
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=100)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(ingest.router, prefix=settings.API_V1_PREFIX)
app.include_router(profile.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(watchlist_api.router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications.router, prefix=settings.API_V1_PREFIX)
app.include_router(payments.router, prefix=settings.API_V1_PREFIX)
app.include_router(reviews.router, prefix=settings.API_V1_PREFIX)
app.include_router(devices.router, prefix=settings.API_V1_PREFIX)
app.include_router(files.router, prefix=settings.API_V1_PREFIX)

# Tourist visa and travel routers
app.include_router(tourist_visa.router, prefix=settings.API_V1_PREFIX)
app.include_router(travel.router, prefix=settings.API_V1_PREFIX)
app.include_router(travel_costs.router, prefix=settings.API_V1_PREFIX)
app.include_router(travel_packages.router, prefix=settings.API_V1_PREFIX)
app.include_router(tour_packages.router, prefix=settings.API_V1_PREFIX)  # INTEGRATED endpoint

# Application Tracker, Visa Risk & Subscription
app.include_router(applications.router, prefix=settings.API_V1_PREFIX)
app.include_router(visa_risk.router, prefix=settings.API_V1_PREFIX)
app.include_router(subscription.router, prefix=settings.API_V1_PREFIX)

# Crawler Pipeline
app.include_router(crawler.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }


@app.get("/health")
async def health_check():
    """Root health check endpoint."""
    return {"status": "healthy", "service": settings.APP_NAME}
