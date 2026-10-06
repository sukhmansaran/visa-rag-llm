# Overseas Visa Chatbot - Backend

Production-grade FastAPI backend for the Overseas Visa Chatbot application. This backend powers RAG-based Q&A, LLM orchestration, web scraping, change detection, notifications, SOP generation, and human review workflows.

## Features

- ✅ **JWT Authentication** - Secure signup, login, and token refresh
- ✅ **PostgreSQL Database** - SQLModel ORM with async support
- ✅ **Redis** - Caching and Celery task queue
- ✅ **Docker Compose** - Local development environment
- ✅ **Alembic Migrations** - Database schema versioning
- ✅ **Health Checks** - Service, database, and Redis monitoring
- 🚧 **RAG Pipeline** - Vector store integration (stub)
- 🚧 **LLM Orchestration** - OpenAI/Gemini integration (stub)
- 🚧 **Web Scraping** - Playwright-based content ingestion
- 🚧 **Change Detection** - Automatic monitoring and notifications
- 🚧 **Payment Integration** - Stripe for human review services

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── auth.py          # Authentication endpoints
│   │       ├── chat.py          # Chat/RAG endpoints (stub)
│   │       ├── health.py        # Health checks
│   │       └── schemas.py       # Pydantic models
│   ├── core/
│   │   ├── config.py            # Settings and configuration
│   │   ├── database.py          # Database session management
│   │   └── security.py          # JWT and password utilities
│   ├── models/
│   │   ├── user.py              # User model
│   │   ├── profile.py           # User profile
│   │   ├── source.py            # Scraping sources
│   │   ├── document.py          # Scraped documents
│   │   ├── vector_chunk.py      # Embedded chunks
│   │   ├── watchlist.py         # User subscriptions
│   │   ├── notification.py      # User notifications
│   │   ├── user_document.py     # SOPs and user docs
│   │   └── review.py            # Human review tickets
│   ├── workers/
│   │   └── celery_app.py        # Celery configuration
│   └── main.py                  # FastAPI application
├── alembic/                     # Database migrations
├── tests/                       # Test suite
├── docker-compose.yml           # Docker services
├── Dockerfile                   # Backend container
├── requirements.txt             # Python dependencies
└── .env.example                 # Environment template
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- PostgreSQL 15 (via Docker)
- Redis 7 (via Docker)

### 1. Clone and Setup

```bash
cd backend
cp .env.example .env
# Edit .env and set your API keys and secrets
```

### 2. Start Services with Docker Compose

```bash
docker-compose up -d
```

This starts:
- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- FastAPI backend on `localhost:8000`
- Celery worker
- Celery beat scheduler

### 3. Run Migrations

```bash
# Inside the backend container or with local Python
alembic upgrade head
```

### 4. Access the API

- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/health
- **Root**: http://localhost:8000/

## Local Development (Without Docker)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start PostgreSQL and Redis

```bash
# Using Docker for databases only
docker-compose up postgres redis -d
```

### 3. Run Migrations

```bash
alembic upgrade head
```

### 4. Start Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start Celery Worker (Optional)

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

## API Endpoints

### Authentication

- `POST /api/v1/auth/signup` - Create new user account
- `POST /api/v1/auth/login` - Authenticate and get tokens
- `POST /api/v1/auth/refresh` - Refresh access token
- `GET /api/v1/auth/me` - Get current user info

### Health Checks

- `GET /health` - Basic health check
- `GET /api/v1/health/db` - Database connectivity
- `GET /api/v1/health/redis` - Redis connectivity

### Chat (Stub)

- `POST /api/v1/chat/answer` - Get AI answer with citations (stub)
- `GET /api/v1/chat/history` - Get chat history (stub)

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ --cov=app --cov-report=html
```

### Run Specific Test File

```bash
pytest tests/test_auth.py -v
```

## Database Migrations

### Create a New Migration

```bash
alembic revision --autogenerate -m "description of changes"
```

### Apply Migrations

```bash
alembic upgrade head
```

### Rollback Migration

```bash
alembic downgrade -1
```

## Environment Variables

Key environment variables (see `.env.example` for complete list):

- `SECRET_KEY` - JWT signing key (change in production!)
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `OPENAI_API_KEY` - OpenAI API key for embeddings and LLM
- `VECTOR_DB_TYPE` - `chroma` or `pinecone`
- `STRIPE_SECRET_KEY` - Stripe API key for payments

## Next Steps

This is the **Phase B** foundation. Next phases will add:

- **Phase C**: Web scraping + embeddings + vector store ingestion
- **Phase D**: Full RAG retrieval + LLM orchestration
- **Phase E**: Profile, SOP, and watchlist APIs
- **Phase F**: Change detection + push notifications
- **Phase G**: Stripe payments + human review workflow
- **Phase H**: Production deployment + security hardening

## License

Proprietary - All rights reserved

## Support

For questions or issues, contact the development team.
