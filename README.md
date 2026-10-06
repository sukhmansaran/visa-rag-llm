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
