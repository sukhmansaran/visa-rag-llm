@echo off
echo ====================================
echo Overseas Visa Chatbot - Quick Start
echo ====================================
echo.

REM Check if .env exists
if not exist .env (
    echo Creating .env file from template...
    copy .env.example .env
    echo.
    echo IMPORTANT: Edit .env and add your API keys:
    echo - OPENAI_API_KEY
    echo - SECRET_KEY (run: openssl rand -hex 32)
    echo.
    pause
)

echo Starting Docker services...
docker compose up -d

echo.
echo Waiting for services to be ready...
timeout /t 10

echo.
echo Running database migrations...
docker compose exec backend alembic upgrade head

echo.
echo Seeding initial data...
docker compose exec backend python scripts/seed_sources.py

echo.
echo ====================================
echo Setup Complete!
echo ====================================
echo.
echo API: http://localhost:8000
echo Docs: http://localhost:8000/docs
echo.
echo Next steps:
echo 1. Test auth: curl http://localhost:8000/api/v1/health
echo 2. See VERIFICATION.md for full testing guide
echo.
pause
