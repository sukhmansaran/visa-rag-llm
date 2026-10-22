# Visa RAG LLM (Pendu) 🍁

> A local-first assistant for Canadian immigration (IRCC) questions: study permits, proof of funds, work rights, post-graduation pathways and visitor visas. Answers are grounded in official canada.ca pages, and hard rules (fund amounts, exemptions, score conversions) come from code, not from the language model.

Everything runs on your own machine: a **FastAPI** backend, a **Next.js 15** frontend, a small local model through **Ollama** (`llama3.2:3b`), **ChromaDB** for retrieval, **PostgreSQL** and **Redis**. No user data is sent to a third-party AI service.

[![CI](https://github.com/sukhmansaran/visa-rag-llm/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sukhmansaran/visa-rag-llm/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](backend/)
[![Node](https://img.shields.io/badge/Node-20.x-green?logo=node.js)](frontend/)
[![Next.js](https://img.shields.io/badge/Next.js-15.5-black?logo=next.js)](frontend/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](backend/alembic/)
[![License](https://img.shields.io/badge/License-AGPL%20v3-orange)](LICENSE)

> **Status:** working local MVP, not production-ready. It gives general information, not legal advice; always confirm with IRCC or a licensed consultant.

---

## 🌟 What it does

### 1. 🛡️ Rules in code, not in the model
Requirements with exact numbers are computed by a deterministic rule engine ([`rule_engine.py`](backend/app/services/rule_engine.py)) that reads dated, source-linked rules from [`ircc_rules.yaml`](backend/app/data/ircc_rules.yaml). The computed facts are handed to the model as binding facts; the model only phrases the answer.
- **Proof of funds:** IRCC's cost-of-living amounts are stored as dated schedules (for example the schedule effective 2026-09-01), so the right amount is chosen for an application date and family size.
- **Language scores:** converts IELTS, CELPIP and PTE scores to Canadian Language Benchmark (CLB) levels.
- **Provincial Attestation Letter (PAL):** checks the exemptions, including the 2026 exemption for master's and doctoral students at public DLIs.
- **Processing times and work rights:** answered from the same rules file; questions that ask for an approval guarantee get an explicit "no one can guarantee approval" fact.

Every rules section records its source URL and when it was last checked; a test fails when a section goes stale.

### 2. 🔎 Grounded answers with citations
- Official pages are fetched, cleaned to their main text and stored as chunks in ChromaDB (cosine similarity).
- [`RetrievalService`](backend/app/services/retrieval.py) reranks chunks by **authority tier**, so an IRCC page outranks a forum post that matches the same words:

| Tier | Source | Weight |
|---|---|---|
| 1 | Official government (canada.ca, IRCC) | 1.0 |
| 2 | DLI universities and colleges | 0.8 |
| 3 | Recognized organizations, provincial programs | 0.6 |
| 4 | Third-party and unverified | 0.3 |

- The model is told to answer only from the retrieved text and to cite it as `[Source 1]`, `[Source 2]`…; when the sources don't cover a question it says so instead of guessing. If nothing relevant is found at all, the model is not called and the user gets a plain "no verified source" reply.
- Answers are cached, and the cache is invalidated when the rules or the knowledge base change.

### 3. 🧱 Guardrails on both sides of the model
All three live in [`services/guardrails/`](backend/app/services/guardrails/):
- **Input** (`InputGuardrail`): blocks prompt injection (including persona and multilingual attempts), harmful requests (document fraud, lying to officers), and off-topic questions before retrieval, with no model call.
- **Output** (`OutputGuardrail`, `StreamingOutputValidator`): checks for code, secrets, system-prompt leaks, file paths and promised immigration outcomes. In streaming mode, text is checked as it arrives, so a violation is stopped before it reaches the user.
- **Legal disclaimer:** added to answers on high-risk topics (refusals, misrepresentation, inadmissibility, enforcement, appeals).

### 4. 🔒 Security and privacy
- JWT auth with refresh-token rotation: each refresh token works once, and logout revokes it.
- Rate limiting per verified user, and per IP on login, signup and refresh. `X-Forwarded-For` is only trusted from configured proxies.
- PII (emails, phone numbers, passport numbers, SIN, UCI, bearer tokens) is redacted from logs and from stored chat messages; user IDs in logs are HMAC-hashed.
- File uploads: magic-byte checks (PDF, JPEG, PNG), a 10 MB limit, metadata stripping, and prompt-injection screening of document text.
- `SECRET_KEY` must be set; short or placeholder keys are rejected at startup.

### 5. 🕷️ Crawler for official sources
Modules in [`services/crawler/`](backend/app/services/crawler/): `frontier`, `robots`, `throttle`, `dedup`, `classifier`, `extractor`, `structurer`, `cache`, `job_manager`, `worker`, `ssrf_validator`.
- Only allowlisted domains (Government of Canada, EduCanada, listed DLIs) can be fetched, and DNS results are checked against private address ranges.
- Respects robots.txt, throttles per host, rotates user agents and supports an optional proxy list.
- Jobs run as Celery tasks; periodic crawls are scheduled with Celery beat.

### 6. 🗄️ Database safety
- Alembic migrations `001`–`013`. Migrating the development database backs it up first, and `scripts/backup_now.py --verify` proves a backup restores (row counts compared table by table).
- Tests never touch the development database: they use allowlisted test databases only, and the migration tests snapshot the dev database and fail if it changes.
- Automatic table creation is off by default and refused for any database outside the allowlist.

### 7. 📏 Measured, not assumed
- [`scripts/eval_rag.py`](backend/scripts/eval_rag.py) runs 63 questions (26 critical) through the full pipeline and scores answers for required facts, forbidden claims and invented numbers; [`scripts/eval_gate.py`](backend/scripts/eval_gate.py) fails a change that makes a passing case fail. The current baseline on `llama3.2:3b` passes 52 of 63 (majority of 3 runs).
- GitHub Actions runs about 1,100 backend tests on every pull request, along with a dependency vulnerability audit, a lint/syntax gate and a frontend lint, build and audit. Tests that need a live Ollama model are skipped in CI and run locally.

---

## 🛠️ Tech stack

| Layer | Technologies |
|---|---|
| **Frontend** | Next.js 15.5 (App Router), React 19, TypeScript, Tailwind CSS, Lucide icons, pnpm 9.15.9 |
| **Backend** | Python 3.12, FastAPI, Uvicorn, SQLModel, Alembic, PyJWT |
| **Data** | PostgreSQL 16, Redis (Memurai on Windows), Celery 5 |
| **AI** | Ollama (`llama3.2:3b` for answers, `nomic-embed-text` for embeddings), ChromaDB 0.5 (embedded) |
| **Crawler** | Playwright, httpx, BeautifulSoup4 |
| **CI** | GitHub Actions (backend and frontend jobs, actions pinned by commit SHA) |

### Frontend pages
| Page | State |
|---|---|
| Chat, Visa risk, Onboarding, Login, Signup | Connected to the backend |
| Dashboard, Applications, Destinations, SOP writer | UI only, showing static sample data |

---

## 📂 Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST endpoints (auth, chat, visa risk, documents, crawler, ingest, ...)
│   │   ├── core/            # Config, database, security, middleware, logging, token store
│   │   ├── data/            # ircc_rules.yaml (dated, source-linked rules)
│   │   ├── models/          # SQLModel tables
│   │   ├── services/        # rag_pipeline, retrieval, rule_engine, llm, vector_store,
│   │   │                    # guardrails/, crawler/, ingestion/
│   │   └── workers/         # Celery app, tasks and schedules
│   ├── alembic/             # Migrations 001–013
│   ├── scripts/             # Source seeding, RAG evaluation, Celery start scripts
│   └── tests/               # pytest suite
├── frontend/
│   └── src/
│       ├── app/             # Next.js pages
│       ├── components/      # Shared UI
│       └── lib/             # Auth helpers
└── .github/workflows/       # CI
```

The `Dockerfile` and `docker-compose.yml` in `backend/` have not been tested recently; the supported setup is the local one below.

---

## 🚀 Quick start (Windows, local)

### Prerequisites
- Python 3.12
- PostgreSQL 16, with two databases: `visa_chatbot` (development) and `visa_chatbot_test` (tests)
- Redis on `127.0.0.1:6379`. On Windows, use [Memurai](https://www.memurai.com/).
- Node.js 20 and pnpm (`npm install -g pnpm@9.15.9`)
- [Ollama](https://ollama.com/) running, with the models pulled:
  ```powershell
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ```

### One command (after the first-time setup below)
```powershell
cd backend
.\scripts\start_all.ps1
```
It checks PostgreSQL (and migrations), Redis, Ollama (and the pinned model builds), settings, the knowledge base,
frontend packages and free ports, and stops with the fix if something is missing. Then it opens a window each for
the API, the three workers, the scheduler and the frontend, waits for the API, and prints the URLs.
`python scripts/preflight.py` runs just the checks.

### 1. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# Set SECRET_KEY in .env (at least 32 characters; placeholders are rejected). Generate one with:
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Also set DATABASE_URL in .env to your visa_chatbot database.
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```
The API runs at `http://localhost:8000`, with Swagger UI at `/docs`.

### 2. Knowledge base
The chatbot answers from the pages you ingest. Register the official sources, then fetch, chunk and embed them (needs Ollama running and Playwright's Chromium):
```powershell
cd backend
playwright install chromium
python scripts/verify_registry.py       # checks every page in app/data/official_sources.yaml is live and allowed
python scripts/sync_sources.py --apply  # registers those pages as sources
python scripts/run_initial_ingestion.py # fetches them and stores the chunks in ChromaDB
```
Without ingested sources, rule-based questions still work, but other answers will say the sources don't cover the question.

### 3. Frontend
```powershell
cd frontend
pnpm install
pnpm dev
```
The web app runs at `http://localhost:3000`.

### 4. Background workers
Run each in its own terminal:
```powershell
cd backend
.\scripts\start_celery_worker.ps1 -Role answers -Name answers1   # chat answers
.\scripts\start_celery_worker.ps1 -Role background -Name bg1     # ingestion, crawling, maintenance
.\scripts\start_celery_worker.ps1 -Role verified -Name verified1 # verified answers (idle unless AGENT_MODE=on)
.\scripts\start_celery_beat.ps1                                  # schedules periodic jobs; run exactly one
```
Workers use `--pool=solo` (Windows has no prefork), so each runs one task at a time. Keeping answers on
their own worker stops a long ingestion or crawl from holding up chat. A single `start_celery_worker.ps1`
with no `-Role` serves every queue, which is fine for a quick try.

The web chat needs the answers worker: without one, the chat shows "Waiting for the answer service" and
gives up after 3 minutes. The direct `/chat/answer` API endpoints don't use workers.

`AGENT_MODE` (in `backend/.env`) controls triage, which decides whether a question needs the slower verified
path: `shadow` (the default) only records the decision in the request trace; `on` sends verified questions to
their own queue and worker, with a place in line shown in the chat and per-user limits
(`VERIFIED_JOBS_IN_FLIGHT_PER_USER`, `VERIFIED_JOBS_PER_HOUR`); `off` skips triage. Questions not in English
get a fixed reply (Pendu answers in English only for now) without a model call.

---

## 🧪 Tests

```powershell
cd backend
pytest                                   # full suite; live-model tests skip if Ollama is not running
pytest tests/test_migration_010_disposable.py -v   # migration up/down on a throwaway database
python scripts/eval_rag.py               # answer-quality evaluation (needs Ollama and an ingested knowledge base)
```

```powershell
cd frontend
pnpm run lint
pnpm run build
```

---

## 📄 License

Licensed under the [GNU Affero General Public License v3.0](LICENSE).
