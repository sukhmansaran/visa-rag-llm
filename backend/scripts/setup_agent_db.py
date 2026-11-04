"""
Create the agent checkpoint database (M5.4) and LangGraph's checkpoint tables in it. Idempotent.

The database is AGENT_CHECKPOINT_URL's, by default DATABASE_URL's server with the database `visa_chatbot_agent`. It is
kept apart from the app database so LangGraph's own schema stays out of the Alembic migrations.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\setup_agent_db.py
  .venv\\Scripts\\python.exe scripts\\setup_agent_db.py --check     # only report whether it is ready
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import checkpoints  # noqa: E402
from app.workers.async_runner import agent_loop_factory  # noqa: E402


async def main(check_only: bool) -> int:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = checkpoints.checkpoint_dsn()
    parts = conninfo_to_dict(dsn)
    name = parts.get("dbname")
    print(f"Agent checkpoint database: {name} on {parts.get('host', 'localhost')}:{parts.get('port', 5432)}")
    admin = make_conninfo(dsn, dbname="postgres")
    async with await psycopg.AsyncConnection.connect(admin, autocommit=True) as conn:
        exists = await (await conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))).fetchone()
        if not exists:
            if check_only:
                print("Not created yet: run scripts/setup_agent_db.py")
                return 1
            await conn.execute(f'CREATE DATABASE "{name}"')  # name from config, not user input
            print("Created the database")
    async with checkpoints.saver() as saver:
        if saver is None:
            print("Could not open the checkpointer (see the warning above)")
            return 1
        async with saver.conn.cursor() as cur:
            await cur.execute("SELECT count(DISTINCT thread_id) AS n FROM checkpoints")
            row = await cur.fetchone()
    print(f"Ready: LangGraph's tables exist; {row['n']} paused or unfinished runs stored")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args().check), loop_factory=agent_loop_factory()))
