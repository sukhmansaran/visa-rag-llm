# Visa RAG LLM (Pendu) 🍁

> An AI-powered immigration intelligence platform and visa guidance assistant focused on Canadian immigration (IRCC), student visas, and tourist travel.

Built with a high-performance **FastAPI** backend, **Next.js 14** modern web interface, hybrid **RAG pipeline** (Ollama / Llama 3.2 + Nomic Embeddings / ChromaDB), automated **crawler infrastructure**, and deterministic visa assessment rules.

---

## 🌟 Key Features

- **🤖 Intelligent Visa Chatbot:** Context-aware Q&A using RAG with IRCC policies and up-to-date immigration guidelines.
- **🛡️ Visa Risk Assessment:** Profile analysis detecting risks, ties to home country, financial readiness, and program fit.
- **📝 Automated SOP Generator:** Drafts tailored Statements of Purpose that directly address profile weaknesses.
- **🕷️ Autonomous Crawler Pipeline:** Crawls official immigration portals and news sources with robots.txt compliance, deduplication, and rate-limiting.
- **🔄 Change Detection & Notifications:** Monitors official policy updates and alerts users to regulatory changes.
- **📊 Modern Dashboard & Metrics:** Clean Next.js 14 UI featuring metrics, application tracking, destination guides, and onboarding.

---

## 🔬 Engineering Detail

The parts that took the longest, and that a feature list hides.

### Retrieval: authority-weighted reranking

Not every source deserves equal trust in an immigration answer. `RetrievalService` assigns each chunk an **authority tier** and reranks on it:

| Tier | Source | Weight |
|---|---|---|
| 1 | Official government — canada.ca, cic.gc.ca, IRCC | 1.0 |
| 2 | DLI universities and colleges | 0.8 |
| 3 | Recognized organizations, provincial programs | 0.6 |
| 4 | Third-party blogs, forums, unverified | 0.3 |

Tiers are read from chunk metadata where present and otherwise inferred from the source domain. A forum post and an IRCC page can both match the same query; only one of them gets to drive the answer.

### Grounding and confidence

- `build_citations` ties each claim in a response back to the chunks that supported it
- `calculate_algorithmic_confidence` scores an answer rather than asserting it
- `sanitize_chunk_text` and `prepare_context` control what reaches the model, and in what form

### Guardrails — three modules, ~44 KB

**Input.** `InputGuardrail.evaluate()` enforces scope before a query reaches retrieval at all, with distinct handling for in-scope visa inquiries and for contextual follow-ups that only make sense given chat history.

**Output.** `OutputGuardrail.validate_output()` runs five independent checks before any response is returned:

| Check | Catches |
|---|---|
| `_check_code` | code blocks leaking into user-facing answers |
| `_check_secrets` | credentials or keys appearing in generated text |
| `_check_prompt_leak` | system prompt disclosure |
| `_check_path_leak` | internal filesystem paths |
| `_check_legal_guarantee` | language that promises an immigration outcome |

Violations are typed via `OutputViolationType` and recorded as security events.

**Streaming.** `StreamingOutputValidator` validates partial output while it is still arriving, with `_check_early_triggers` catching a violation before the user sees it. Validating a finished response is straightforward; validating one token by token mid-stream is the harder problem, and the one a streaming UI actually has.

**Legal disclaimer.** Its own module — an immigration tool that reads as legal advice is a liability whatever the model intended.

### Crawler — 13 modules

`frontier` · `robots` · `throttle` · `dedup` · `classifier` · `extractor` · `structurer` · `cache` · `job_manager` · `worker` · `portal_configs`

Politeness and correctness are first-class rather than afterthoughts: robots.txt compliance, per-host throttling, URL frontier management, content deduplication, and page classification ahead of extraction. Change detection sits on top and flags when a policy source has genuinely changed.

### Test suite — 36 files

Coverage is weighted toward what is hard to get right rather than what is easy to assert:

- **Guardrails and grounding** — `test_citation_delimitation`, `test_output_guardrail`, `test_streaming_output_guardrail`, `test_input_guardrail`, `test_legal_disclaimer`
- **Retrieval** — `test_rag_integration`, `test_retrieval_service`, `test_authority_tiering`, `test_deduplicator`, `test_embeddings_service`
- **Crawling** — `test_crawl_frontier`, `test_crawler_worker`, `test_robots_checker`, `test_throttle_manager`, `test_page_classifier`
- **Ingestion** — `test_ingestion_orchestrator`, `test_ingestion_pipeline`, `test_unified_pipeline`, `test_official_fetcher_and_normalizer`
- **Security** — `test_logging_pii_redaction`, `test_file_upload_security`, `test_user_isolation_and_security`, `test_database_init_safety`
- **End to end** — `test_live_llm_e2e`, `test_migration_010_disposable`

---

## 🛠️ Tech Stack

### Backend
- **Framework:** FastAPI (Python 3.11+)
- **Database & ORM:** PostgreSQL + SQLModel + Alembic migrations
- **Cache & Task Queue:** Redis + Celery
- **Vector Database:** ChromaDB (with Pinecone support)
- **AI / LLM Stack:** Ollama (`llama3.2:3b`) + embeddings (`nomic-embed-text`) / Google Gemini support

### Frontend
- **Framework:** Next.js 14 (App Router) + React 18 + TypeScript
- **Styling:** Tailwind CSS + Lucide Icons
- **Package Manager:** pnpm

---

## 📂 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/v1/         # Modular REST endpoints (chat, auth, visa-risk, crawler, etc.)
│   │   ├── core/           # Config, database sessions, auth & security
│   │   ├── models/         # SQLModel database schemas
│   │   ├── services/       # RAG pipeline, crawler, SOP generator, LLM orchestrator
│   │   └── workers/        # Celery asynchronous tasks & scheduled monitors
│   ├── alembic/            # Database migration revisions
│   ├── scripts/            # Seed data & system verification utilities
│   ├── tests/              # Pytest test suite
│   ├── Dockerfile          # Backend containerization
│   └── docker-compose.yml  # PostgreSQL, Redis & Backend service definitions
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router (dashboard, chat, visa-risk, sop)
│   │   └── components/     # UI components & layouts
│   ├── package.json        # Frontend dependencies
│   └── tailwind.config.ts  # Tailwind theme configuration
├── docs/                   # Architecture & RAG cost optimization documentation
├── LICENSE                 # GNU Affero General Public License v3.0
└── PROJECT_STATUS.md       # Comprehensive architecture inventory & roadmap
```

---

## 🚀 Getting Started

### Prerequisites
- Docker & Docker Compose
- Node.js 18.17+ & pnpm (for frontend)
- Python 3.11+ (for local backend development)
- [Ollama](https://ollama.ai/) running locally with models:
  ```bash
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ```

---

### Option A: Running with Docker Compose (Recommended)

1. **Configure environment:**
   ```powershell
   cd backend
   Copy-Item .env.example .env
   ```
   *(Update any custom settings in `backend/.env`)*

2. **Start backend services:**
   ```powershell
   docker compose up -d --build
   docker compose exec backend alembic upgrade head
   ```
   API runs at: `http://localhost:8000` (Interactive docs at `/docs`)

3. **Start the frontend:**
   ```powershell
   cd ../frontend
   pnpm install
   pnpm dev
   ```
   Web interface runs at: `http://localhost:3000`

---

### Option B: Local Python Development

1. **Backend setup:**
   ```powershell
   cd backend
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   Copy-Item .env.example .env
   alembic upgrade head
   python -m uvicorn app.main:app --reload --port 8000
   ```

2. **Seed sample data (optional):**
   ```powershell
   python seed_tourist_data.py
   python scripts/seed_sources.py
   ```

3. **Frontend setup:**
   ```powershell
   cd ../frontend
   pnpm install
   pnpm dev
   ```

---

## 🧪 Running Tests

Run the backend test suite:

```powershell
cd backend
pytest
```

---

## 📄 License

This project is licensed under the terms of the [GNU Affero General Public License v3.0](LICENSE).
