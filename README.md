# Pendu

Pendu is a Canada-focused student visa assistant. The repository contains a FastAPI backend for chat, visa guidance, document generation, and crawling, alongside a Next.js web interface. Some frontend screens are still demo or locally computed experiences; see [PROJECT_STATUS.md](PROJECT_STATUS.md) for the current implementation inventory.

## Stack

- Backend: Python 3.11+, FastAPI, PostgreSQL, Redis, and Alembic
- Frontend: Node.js 18.17+, Next.js 14, and pnpm 9.15.9 (via Corepack)
- Local services: Docker Compose

## Quick Start

### 1. Configure the backend

```powershell
cd backend
Copy-Item .env.example .env
```

Edit `backend/.env` and set a unique `SECRET_KEY` and any provider credentials you intend to use. Never commit `.env` or put real credentials in source files.

### 2. Start backend services

From the `backend` directory:

```powershell
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

The API is available at <http://localhost:8000>, with interactive docs at <http://localhost:8000/docs>.

### 3. Start the web app

In another terminal, from the repository root:

```powershell
cd frontend
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

Open <http://localhost:3000>. The Next.js development server proxies `/api/v1` requests to the backend on port 8000.

## Tests

Run the backend tests from `backend` after installing `requirements.txt`:

```powershell
python -m pytest
```

## Configuration

The backend reads configuration from `backend/.env`; `backend/.env.example` lists the available settings. Docker Compose supplies the container database and Redis URLs. For local development, install and configure equivalent PostgreSQL and Redis services.

## GitHub Upload Warnings

Review [GITHUB_UPLOAD_WARNINGS.md](GITHUB_UPLOAD_WARNINGS.md) before publishing this repository. Its existing Git history contains credential-shaped values and generated frontend files that are not removed by the current `.gitignore` rules.

## Security

Treat API keys, passwords, signing keys, and user data as private. If a credential was committed at any point, revoke or rotate it; deleting it from the current files does not remove it from Git history. Review the full history before publishing this repository publicly.
