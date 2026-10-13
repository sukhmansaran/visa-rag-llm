# Visa RAG LLM (Pendu) 🍁

> An enterprise-grade AI immigration intelligence platform and automated guidance assistant focused on Canadian immigration (IRCC), student permits, study-to-work transitions, and tourist travel.

Built with a high-performance **FastAPI** backend, **Next.js 15** App Router interface, deterministic **statutory rule engine**, bi-directional **security firewalls**, autonomous **crawler pipeline**, and automated **CI/CD infrastructure**.

[![CI Status](https://img.shields.io/badge/CI%2FCD-Passing-brightgreen?logo=github-actions)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Tests-pytest-brightgreen)](backend/tests/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue?logo=python)](backend/)
[![Node](https://img.shields.io/badge/Node-20.x-green?logo=node.js)](frontend/)
[![Next.js](https://img.shields.io/badge/Next.js-14.x-black?logo=next.js)](frontend/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](backend/alembic/)
[![License](https://img.shields.io/badge/License-AGPL%20v3-orange)](LICENSE)

---

## 🌟 Key Features & Engineering Innovations

### 1. 🛡️ Deterministic Rule Primacy
Statutory requirements under Canadian immigration regulations are evaluated deterministically in Python code—completely bypassing probabilistic LLM hallucinations:
- **Proof of Funds Calculator:** Encodes 2024 IRCC cost-of-living updates ($20,635 base + tuition + family dependents) with currency conversion.
- **Language Conversion Engine:** Maps IELTS General/Academic, CELPIP-General, and PTE Core scores to Canadian Language Benchmark (CLB 4–10).
- **Provincial Attestation Letter (PAL):** Evaluates exemption eligibility (Master's/PhD, primary/secondary school, in-Canada extensions).

### 2. 🧱 Bi-Directional Security Firewalls
- **Deterministic Input Guardrail:** Detects prompt injections, code generation requests, role-play jailbreaks (DAN), and out-of-scope non-visa topics pre-retrieval ($<15$ms response time, 0 LLM tokens).
- **Sentence-Buffered Streaming Output Shield:** Validates generated text sentence-by-sentence in real-time, blocking internal prompt leaks, system delimiters, filesystem paths, credentials, and unwarranted legal guarantees.
- **Statutory Legal Disclaimer Engine:** Appends context-aware non-legal advice disclaimers compliant with Canadian immigration regulatory guidelines.

### 3. 🔒 Privacy & Secure File Ingestion
- **Recursive PII Redaction:** Scrubs passports, IRCC Client ID/UCIs, Canadian SINs, phone numbers, emails, and bearer auth tokens across all server logs.
- **Salted SHA-256 Telemetry:** Hashes user IDs before persisting structured audit log events.
- **Magic-Byte Document Ingestion:** Verifies file signatures (PDF `%PDF-`, JPEG `\xFF\xD8\xFF`, PNG `\x89PNG`), enforces 10MB limits, strips EXIF/IPTC/PDF metadata, and neutralizes prompt injections inside uploaded resumes and bank statements.

### 4. 🕷️ Autonomous Crawler Pipeline & Anti-Bot Subsystem
- Scrapes official government web sources (`canada.ca`, `cic.gc.ca`) with robots.txt compliance.
- Employs token bucket rate limiting (`throttle_manager.py`), rotating TLS browser fingerprints, and proxy pools to prevent crawler blacklisting.
- Database revisions 009 (`crawler_pipeline`) and 010 (`crawler_anti_bot`) track jobs, seeds, page logs, and change events.

### 5. 🗄️ Database Lifecycle Safeguards & Disposable Isolation
- **Development Database Protection:** Tests never modify the development database (`visa_chatbot`): migration tests snapshot its revision and tables and fail if anything changes. Upgrade it deliberately with `alembic upgrade head` (currently at `010`).
- **`init_db()` Allowlist:** `DATABASE_AUTO_CREATE_TABLES` defaults to `False`. Table auto-creation via `SQLModel.metadata.create_all()` is blocked unless the database is explicitly listed in `DISPOSABLE_DATABASE_ALLOWLIST`.
- **Disposable Lifecycle Runner:** Automated tests dynamically spawn and drop disposable databases (`visa_chatbot_disposable_migration_test`) for full 001 $\to$ 010 upgrade and downgrade testing.

### 6. ⚙️ Dual-Job Continuous Integration (CI/CD)
- GitHub Actions pipeline (`.github/workflows/ci.yml`) runs concurrent `backend` and `frontend` jobs.
- Uses AWS ECR Public PostgreSQL 16 mirror (`public.ecr.aws/docker/library/postgres:16`) for unthrottled runner performance.
- Pins all third-party actions by immutable commit SHAs.

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

| Layer | Technologies |
|---|---|
| **Frontend** | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, Lucide Icons, pnpm 9.15.9 |
| **Backend** | FastAPI, Python 3.11 / 3.12, Uvicorn, SQLModel ORM, Alembic |
| **Databases & Cache** | PostgreSQL 16, Redis 7, Celery asynchronous task queue |
| **Vector Search & AI** | ChromaDB (embedded, persistent), Ollama (`llama3.2:3b`, `nomic-embed-text`) |
| **Crawler** | Playwright, BeautifulSoup4, Token-bucket rate limiting |
| **CI/CD & DevOps** | GitHub Actions, Docker, Docker Compose, AWS ECR Public mirrors |

---

## 📂 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/v1/         # Modular REST endpoints (chat, risk, crawler, files, auth)
│   │   ├── core/           # Config, database, security, input/output guardrails, logging
│   │   ├── models/         # SQLModel database schemas (user, crawler, visa, doc)
│   │   └── services/       # Unified RAG, rule engine, LLM orchestrator, crawler worker
│   ├── alembic/            # Database migrations (001 through 010)
│   ├── tests/              # Automated unit, integration, guardrail, and red-team tests
│   └── Dockerfile          # Backend containerization
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router (dashboard, chat, visa-risk, sop, destinations)
│   │   └── components/     # Reusable UI components & layouts
│   ├── package.json        # Frontend dependencies (pnpm 9.15.9)
│   └── next.config.mjs     # Remote image patterns & Next.js config
├── docs/                   # Authoritative architecture & database documentation
├── project_plan/           # Milestones, audit logs, incident post-mortems, roadmaps
└── .github/workflows/      # Automated CI/CD workflow definitions
```

---

## 🚀 Quick Start

### Prerequisites
- PostgreSQL 16 running locally
- Redis on `127.0.0.1:6379` — on Windows use [Memurai](https://www.memurai.com/) (Redis-compatible service)
- Node.js 20 & `pnpm` (`npm install -g pnpm@9.15.9`)
- Python 3.12
- [Ollama](https://ollama.ai/) running locally with models:
  ```bash
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ```

### Running Locally

1. **Backend Setup:**
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   Copy-Item .env.example .env
   # REQUIRED: set SECRET_KEY in .env (min 32 chars; placeholders are rejected at startup)
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```
   API runs at: `http://localhost:8000` (Swagger UI at `/docs`)

2. **Frontend Setup:**
   ```powershell
   cd ../frontend
   pnpm install
   pnpm dev
   ```
   Web interface runs at: `http://localhost:3000`

3. **Background workers (ingestion, crawling, scheduled jobs)** — each in its own terminal:
   ```powershell
   cd backend
   .\scripts\start_celery_worker.ps1   # executes jobs (uses --pool=solo; Windows has no prefork)
   .\scripts\start_celery_beat.ps1     # schedules periodic jobs; run exactly one
   ```
   The API works without workers, but ingestion/crawl endpoints and scheduled jobs need them.

---

## 🧪 Running Automated Tests

### Backend Test Suite
```powershell
cd backend
pytest
```

### Run Migration Lifecycle Tests (Disposable Database)
```powershell
pytest tests/test_migration_010_disposable.py -v
```

### Run Frontend Lint & Build
```powershell
cd ../frontend
pnpm run lint
pnpm run build
```

---

## 📚 Complete Project Documentation Index

For exhaustive context, refer to the dedicated markdown documents:

| Documentation File | Description & Contents |
|---|---|
| [PROJECT_STATUS.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/PROJECT_STATUS.md) | Executive status, system architecture, test metrics, and current readiness matrix. |
| [backend/README.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/backend/README.md) | Backend engineering manual, API catalog, directory layout, and security controls. |
| [docs/ARCHITECTURE.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/docs/ARCHITECTURE.md) | Authoritative multi-tier system architecture and dataflow diagrams. |
| [docs/DATABASE_LIFECYCLE_AND_SAFEGUARDS.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/docs/DATABASE_LIFECYCLE_AND_SAFEGUARDS.md) | Migrations 001–010, dev DB protection, `init_db()` allowlist, and disposable DB testing. |
| [docs/RAG_COST_OPTIMIZATION.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/docs/RAG_COST_OPTIMIZATION.md) | Mathematical analysis of token reductions and cost savings via deterministic rule bypass. |
| [project_plan/AUDIT_LOG.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/project_plan/AUDIT_LOG.md) | Granular chronological audit log of all completed engineering tasks and verification evidence. |
| [project_plan/detailed_tasks.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/project_plan/detailed_tasks.md) | Granular task checklists across all Milestones (1–6) and engineering phases. |
| [project_plan/CI_CD_INCIDENT_REPORT.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/project_plan/CI_CD_INCIDENT_REPORT.md) | Post-mortem analysis of all 6 CI/CD errors (Action pins, Docker Hub 429, ESLint, devDeps, timing race). |
| [project_plan/ROADMAP_AND_REMAINING_WORK.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/project_plan/ROADMAP_AND_REMAINING_WORK.md) | Detailed operational plan for remaining work: Milestone 5, Milestone 6, OWASP IDOR, and production gate. |
| [GITHUB_UPLOAD_WARNINGS.md](file:///d:/projects/llm%20chatbot/llm%20chatbot/pendu/GITHUB_UPLOAD_WARNINGS.md) | Security advisory regarding historical Git commit sanitization prior to public repository upload. |

---

## 📄 License

This project is licensed under the terms of the [GNU Affero General Public License v3.0](LICENSE).
