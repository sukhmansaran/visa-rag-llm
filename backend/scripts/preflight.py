"""
Check that everything Pendu needs is ready, and say how to fix what isn't (M0.17). Used by start_all.ps1.

    cd backend
    python scripts/preflight.py

Each check is OK, WARN (Pendu runs, but something is off) or FAIL (Pendu can't run). Exit code 1 on any FAIL.
Never prints secrets.
"""

import asyncio
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, List

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


async def check_settings() -> Check:
    if not (BACKEND / ".env").exists():
        return Check("Settings", FAIL, "backend/.env is missing", "Copy-Item .env.example .env, then set SECRET_KEY "
                     "and DATABASE_URL (see README, Quick start)")
    try:
        from app.core.config import settings  # validates SECRET_KEY etc.
    except Exception as err:
        return Check("Settings", FAIL, f"backend/.env is invalid: {type(err).__name__}: {str(err)[:200]}",
                     "Fix the value named above in backend/.env")
    return Check("Settings", OK, f"loaded ({settings.APP_NAME})")


async def check_database() -> Check:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            try:
                current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                current = None
    except Exception as err:
        return Check("PostgreSQL", FAIL, f"can't connect ({type(err).__name__})",
                     "Start PostgreSQL 16 (Services -> postgresql-x64-16) and check DATABASE_URL in backend/.env")
    finally:
        await engine.dispose()

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    head = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()
    if current != head:
        return Check("PostgreSQL", FAIL, f"database is at migration {current}, code expects {head}",
                     "cd backend; .\\.venv\\Scripts\\python.exe -m alembic upgrade head   (backs up first)")
    return Check("PostgreSQL", OK, f"connected, migrations up to date ({head})")


async def check_redis() -> Check:
    import redis.asyncio as aioredis

    from app.core.config import settings

    client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
    try:
        await client.ping()
    except Exception as err:
        return Check("Redis", FAIL, f"can't connect ({type(err).__name__})",
                     "Start Memurai (Services -> Memurai) or Redis on 127.0.0.1:6379")
    finally:
        await client.aclose()
    return Check("Redis", OK, "connected")


async def check_ollama() -> Check:
    from app.services.model_pins import check_pins

    report = await check_pins()
    if not report.ollama_reachable:
        return Check("Ollama", FAIL, "not reachable", "Start Ollama (the tray app, or `ollama serve`)")
    missing = [m.model for m in report.models if m.status == "not_installed"]
    if missing:
        return Check("Ollama", FAIL, f"models not installed: {', '.join(missing)}",
                     "; ".join(f"ollama pull {m}" for m in missing))
    if not report.ok:
        return Check("Ollama", WARN, "; ".join(report.problems()),
                     "Answers may differ from the evaluated build: run the full eval, then pin_models.py --accept")
    return Check("Ollama", OK, "running, all models match their pinned builds")


async def check_knowledge_base() -> Check:
    from app.services.vector_store import vector_store

    try:
        count = await vector_store.content_version()
    except Exception as err:
        return Check("Knowledge base", WARN, f"can't read it ({type(err).__name__})", "See README, Knowledge base")
    if count.endswith("-0"):
        return Check("Knowledge base", WARN, "empty: answers will say the sources don't cover the question",
                     "python scripts/sync_sources.py --apply; python scripts/run_initial_ingestion.py")
    return Check("Knowledge base", OK, count.replace("chroma-", "") + " chunks")


async def check_frontend() -> Check:
    modules = BACKEND.parent / "frontend" / "node_modules" / "next"
    if not modules.exists():
        return Check("Frontend", FAIL, "packages not installed", "cd frontend; pnpm install")
    return Check("Frontend", OK, "packages installed")


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def check_ports() -> Check:
    busy = [str(p) for p in (8000, 3000) if _port_in_use(p)]
    if busy:
        return Check("Ports", WARN, f"already in use: {', '.join(busy)} (is Pendu already running?)",
                     "Close the old Pendu windows, or another program on that port")
    return Check("Ports", OK, "8000 and 3000 free")


CHECKS: List[Callable[[], Awaitable[Check]]] = [
    check_settings, check_database, check_redis, check_ollama, check_knowledge_base, check_frontend, check_ports,
]


async def run_checks(checks=None) -> List[Check]:
    results = []
    for check in checks or CHECKS:
        try:
            result = await check()
        except Exception as err:  # a check must never crash the preflight
            result = Check(check.__name__.replace("check_", "").title(), FAIL, f"{type(err).__name__}: {err}")
        results.append(result)
        if result.name == "Settings" and result.status == FAIL:
            break  # nothing else can load without settings
    return results


def main() -> int:
    results = asyncio.run(run_checks())
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"[{r.status:<4}] {r.name:<{width}}  {r.detail}")
        if r.fix and r.status != OK:
            print(f"       {'':<{width}}  fix: {r.fix}")
    failed = [r for r in results if r.status == FAIL]
    print("\nReady to start." if not failed else f"\nNot ready: {len(failed)} problem(s) above must be fixed first.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
