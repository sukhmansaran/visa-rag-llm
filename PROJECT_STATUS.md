# Pendu Project Status

Updated: 2026-10-05

## Executive summary

Pendu is now a multi-layer immigration and travel assistant project with a FastAPI backend, a Next.js frontend, a PostgreSQL/Redis data layer, and a growing crawler pipeline. The app is no longer just a static frontend mock; it has actual application APIs, database models, document generation, tourist-visa logic, and web-crawler infrastructure.

Current project status: feature-rich internal MVP foundation, not yet production-ready for public launch.

## Current architecture

### Frontend
- Next.js 14 app router
- React + TypeScript + Tailwind
- Routes cover onboarding, dashboard, visa-risk, applications, destinations, SOP, chat, and demo metrics
- Local dev is configured to proxy `/api/v1` requests to the backend on port 8000

### Backend
- FastAPI service with modular API route files under `backend/app/api/v1/`
- Core modules for auth, profile, chat, documents, payments, reviews, notifications, applications, tourist visa, travel, files, and crawler operations
- SQLModel + Alembic migrations with PostgreSQL
- Redis + Celery used for background jobs and task orchestration
- Service layer includes scraping, embeddings, retrieval, rules, LLM interaction, notifications, and crawler logic

### Data and infrastructure
- PostgreSQL for relational data
- Redis for cache and queueing
- Chroma as the default vector store option; Pinecone is still a production flag
- Docker Compose for local services
- Environment variables managed from `backend/.env` using `.env.example` as the template

### AI and LLM stack
- Primary LLM provider: local Ollama inference server
- Chat/completion model: `llama3.2:3b`
- Embedding model: `nomic-embed-text`
- Base URL: `http://localhost:11434`
- Retrieval flow: query embeddings generated locally and matched against stored vector data before generation
- Generation flow: the app uses the local LLM for chat responses, SOP generation, itinerary generation, rule-based RAG response synthesis, and summarization tasks
- In practice, the current implementation is an Ollama-backed RAG stack rather than a direct Google Gemini integration

## Recent project changes

The repository includes a broader set of implemented features compared with the earlier status report:

- New crawler pipeline additions under `backend/app/services/crawler/`, `backend/app/models/`, and `backend/app/api/v1/crawler.py`
- New crawler-related tests added under `backend/tests/`
- Additional backend API modules for crawler jobs, seed URLs, tourist visa, travel packages, and related schemas
- Hardened repo hygiene: `.gitignore` covers `.env`, `.venv`, `node_modules`, `.next`, and generated data folders
- README and warning docs updated to call out upload safety and GitHub history cleanup requirements
- Frontend package manager pinned to pnpm 9.15.9 to match the lockfile and avoid toolchain drift

## Product scope

Pendu remains centered on Canadian visa guidance, with the current product positioning focused on student-visa assistance and immigration risk reduction. The app combines:

- deterministic rules for visa risk analysis
- retrieval-based Q&A over immigration/document content using local embedding + vector retrieval
- document generation for SOP-related flows
- travel and tourist-visa planning features
- crawler-based content monitoring for official sources and change detection
- local Ollama-backed LLM responses for assistant chat and summarization tasks

## Current readiness

### Ready for
- Local development and demos
- Backend/API iteration
- Feature testing in a controlled environment
- Internal validation and iteration

### Not ready for
- Public open-source release without a Git history cleanup
- Production deployment without security hardening
- Real customer traffic without auth, validation, and operational checks

## Known gaps and risk areas

These are the main issues still worth addressing before a launch-grade milestone:

1. Authentication is still partly demo-user based in several routes.
2. Some write APIs do not enforce admin-only or authenticated access.
3. Several flows still use in-memory or mock behavior instead of fully persisted production state.
4. Payments, reviews, and notification flows need validation against the real schema and business rules.
5. The crawler and ingestion pipeline should be reviewed for auth, authorization, and security boundaries.
6. Generated files like `node_modules` and `.next` must remain excluded from Git before public push.
7. Historical credential-like values in earlier Git commits need cleanup before any public repository upload.

## Recommended next milestones

### Near-term
- Finalize auth and authorization boundaries across all API routes
- Remove or isolate demo-user bypasses from protected features
- Validate database schema consistency across models and migrations
- Re-test crawler and ingestion flows with seeded data
- Confirm env vars, secrets, and file storage handling for local and deployment modes

### Medium-term
- Add real user/session auth across the frontend and backend
- Replace remaining mock flows with live API-backed data
- Add stronger validation and test coverage for payments, documents, reviews, and crawler endpoints
- Establish deployment configuration and operational monitoring

### Longer-term
- Production hardening for security, data retention, and observability
- Public release preparation after history cleanup and credential rotation
- Documentation for onboarding, deployment, and maintenance

## GitHub / publication note

This repository is not yet safe to publish as-is from the current Git history. The project now includes cleanup guidance in the warning docs, but any public upload still requires a careful sweep of old commit history for credentials and generated artifacts.

## Bottom line

The project has moved well beyond the original prototype. It is now a real application foundation with a broad feature set, but it still needs a disciplined pass on security, auth, and Git hygiene before a public GitHub release.
