# Overseas Visa Chatbot — Backend Engineering Guide

**Module:** `backend`  
**Framework:** FastAPI (Python 3.11 / 3.12)  
**Database:** PostgreSQL 16 (SQLModel ORM + Alembic)  
**Cache & Tasks:** Redis 7 + Celery  
**AI & Vectors:** Local Ollama (`llama3.2:3b`, `nomic-embed-text`) + ChromaDB (embedded, persistent)  
**Tests:** `pytest` (see section 4)  

---

## 1. System Overview

The `backend` service powers the core intelligence, security firewalls, and data orchestration for the Visa RAG platform. It provides RESTful APIs for conversational guidance, visa risk analysis, document generation, secure file processing, and autonomous web crawling.

### Core Architectural Pillars
- **Deterministic Rule Primacy:** Calculations for Proof of Funds, CLB language conversions, and Provincial Attestation Letters (PAL) are computed deterministically without LLM hallucination.
- **Bi-Directional Security Firewalls:** Pre-retrieval input guardrails reject prompt injections and code generation requests; sentence-buffered streaming output guardrails shield internal prompts, credentials, and unwarranted legal guarantees.
- **Privacy & Audit Telemetry:** Recursive PII redactor sanitizes server logs; user identifiers are hashed with salted SHA-256 in audit logs.
- **Alembic Database Lifecycles & Safeguards:** Schema versions 001 through 010 manage all relational entities. Table auto-creation is disabled on startup, and disposable databases are used for lifecycle tests to preserve development database integrity.

---

## 2. Directory Structure

```
backend/
├── alembic/
│   ├── versions/                # Migration scripts 001 to 010
│   └── env.py                   # Migration engine & URL precedence configuration
├── app/
│   ├── api/v1/                  # RESTful API Endpoints
│   │   ├── auth.py              # JWT authentication & session refresh
│   │   ├── chat.py              # Synchronous & streaming RAG chat endpoints
│   │   ├── visa_risk.py         # Profile risk scoring & refusal factor analysis
│   │   ├── crawler.py           # Crawler jobs, seeds, scheduling & metrics
│   │   ├── files.py             # Secure file upload & sanitization
│   │   ├── documents.py         # User documents & SOP management
│   │   ├── profile.py           # User applicant profile management
│   │   ├── applications.py      # Immigration application tracker
│   │   ├── tourist_visa.py      # Tourist entry requirements & packages
│   │   ├── travel.py            # Travel guides & cost estimation
│   │   └── health.py            # System health & connectivity checks
│   ├── core/                    # Core Infrastructure & Security
│   │   ├── config.py            # Pydantic environment settings
│   │   ├── database.py          # SQLModel session factory & init_db safeguards
│   │   ├── security.py          # Password hashing & JWT token operations
│   │   ├── input_guardrail.py   # Adversarial prompt injection & intent firewall
│   │   ├── output_guardrail.py  # Leakage shield & guarantee detector
│   │   ├── streaming_output_guardrail.py # Sentence-buffered streaming guardrail
│   │   ├── legal_disclaimer.py  # Context-aware statutory disclaimers
│   │   └── logging_config.py    # Recursive PII redactor & salted hashing logger
│   ├── models/                  # SQLModel Relational Schemas
│   │   ├── user.py              # User accounts & credentials
│   │   ├── profile.py           # Applicant demographic & academic profiles
│   │   ├── crawler.py           # Crawler seeds, jobs, metrics, and logs
│   │   ├── crawler_anti_bot.py  # Anti-bot domains, fingerprints, and proxies
│   │   ├── document.py          # Scraped policy pages
│   │   ├── vector_chunk.py      # Vector chunk references
│   │   ├── user_document.py     # SOPs and uploaded documents
│   │   ├── visa_risk.py         # Risk scores & assessment factors
│   │   ├── notification.py      # User notifications & policy updates
│   │   └── review.py            # Human review tickets & payments
│   ├── services/                # Business Logic & AI Services
│   │   ├── unified_rag.py       # Master RAG orchestrator with memory
│   │   ├── rule_engine.py       # Deterministic Proof of Funds, CLB & PAL math
│   │   ├── llm.py               # Ollama LLM client (shared HTTP pool, 503 on outage)
│   │   ├── embeddings.py        # Nomic vector embedding generation
│   │   ├── retrieval.py         # ChromaDB similarity search
│   │   ├── file_service.py      # Magic-byte validation & injection sanitizer
│   │   ├── sop_generator.py     # Statement of Purpose drafting engine
│   │   └── crawler/             # Autonomous Web Scraper Subsystem
│   │       ├── worker.py        # Playwright & BeautifulSoup fetch worker
│   │       ├── throttle_manager.py # Domain-specific token bucket rate limiter
│   │       ├── frontier.py      # URL queue & seed dispatcher
│   │       ├── robots.py        # Robots.txt parser & compliance enforcer
│   │       └── dedup.py         # SHA-256 content deduplication
│   └── main.py                  # FastAPI application entrypoint & middleware
├── tests/                       # Automated Pytest Suite
│   ├── test_input_guardrail.py  # 103 prompt injection & code test cases
│   ├── test_unified_pipeline.py # RAG orchestrator & context memory tests
│   ├── test_output_guardrail.py # Secret leakage & guarantee shield tests
│   ├── test_streaming_output_guardrail.py # Sentence-buffering tests
│   ├── test_rule_engine.py      # Proof of funds, CLB, and PAL tests
│   ├── test_logging_pii_redaction.py # Recursive PII redactor tests
│   ├── test_file_upload_security.py # Magic-byte & injection upload tests
│   ├── test_migration_010_disposable.py # Disposable DB lifecycle tests
│   ├── test_throttle_manager.py # Rate limiter & timing race tests
│   └── conftest.py              # Test fixtures & disposable DB configuration
├── alembic.ini                  # Alembic CLI settings
├── requirements.txt             # Python dependencies
└── .env.example                 # Environment variables template
```

---

## 3. Quick Start & Local Setup

### Prerequisites
- Python 3.11 or 3.12
- PostgreSQL 16
- Redis 7
- [Ollama](https://ollama.com/) running locally with models:
  ```bash
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ```

### Step 1: Environment Setup
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# REQUIRED: set SECRET_KEY in .env (min 32 chars; placeholders are rejected at startup)
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Step 2: Running Migrations
```powershell
# Applies all schema revisions (001 through 010) to the configured database
alembic upgrade head
```

### Step 3: Starting the API Server
```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Interactive API Documentation: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/api/v1/health`

---

## 4. Running the Test Suite

The backend test suite covers unit, integration, guardrail, red-team, and migration cases.

### Run the Complete Test Suite
```powershell
pytest
```

### Run Migration Lifecycle Tests (Disposable Database)
```powershell
pytest tests/test_migration_010_disposable.py -v
```

### Run Security & Guardrail Test Suites
```powershell
pytest tests/test_input_guardrail.py tests/test_output_guardrail.py tests/test_logging_pii_redaction.py tests/test_file_upload_security.py -v
```

### Run Deterministic Rule Engine Tests
```powershell
pytest tests/test_rule_engine.py -v
```

---

## 5. Security & Safety Controls

1. **Development Database Protection:** Tests never modify the development database (`visa_chatbot`): migration tests snapshot its revision and tables and fail if anything changes. Upgrade it deliberately with `alembic upgrade head` (currently at `010`). Migration lifecycle tests dynamically spawn and drop disposable databases (`visa_chatbot_disposable_migration_test`), and the whole test suite runs against `visa_chatbot_test`.
2. **`init_db()` Allowlist:** `DATABASE_AUTO_CREATE_TABLES` defaults to `False`. Table creation through `SQLModel.metadata.create_all()` is blocked unless the database name is explicitly present in `DISPOSABLE_DATABASE_ALLOWLIST` and `ENVIRONMENT="test"`.
3. **Magic-Byte Document Ingestion:** The file service verifies magic bytes (`%PDF-`, `\xFF\xD8\xFF`, `\x89PNG`), limits uploads to 10MB, strips EXIF/PDF metadata, and redacts embedded prompt injections before text extraction.
4. **PII Log Redaction:** All application loggers scrub passports, SINs, UCIs, phone numbers, emails, and auth tokens automatically.
