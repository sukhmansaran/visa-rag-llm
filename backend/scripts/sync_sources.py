"""
Bring the sources table in line with the official source registry (M0.10).

    cd backend
    python scripts/sync_sources.py            # dry run: print the plan, change nothing
    python scripts/sync_sources.py --apply    # apply it in one transaction

Creates sources for new registry entries, updates registry fields (URL, title, tier, topics, freshness) on
existing ones, and deactivates sources listed under `excluded`. Sources not in the registry are reported,
never changed. It never touches documents or the knowledge base: ingest new sources as usual afterwards.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services.source_registry import REGISTRY_PATH, load_registry, plan_sync  # noqa: E402


def _short(value, width=60) -> str:
    text = str(value)
    return text if len(text) <= width else text[:width - 3] + "..."


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--apply", action="store_true", help="apply the plan (default: dry run)")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    async with AsyncSessionLocal() as db:
        sources = list((await db.execute(select(Source))).scalars().all())
        changes = plan_sync(registry, sources)

        actionable = [c for c in changes if c.kind != "unregistered"]
        for change in changes:
            target = change.registry_id or f"source {change.source_id}"
            print(f"{change.kind.upper():<13} {target}  {change.url}" + (f"  -- {change.note}" if change.note else ""))
            for name, value in change.fields.items():
                if change.kind == "update":
                    print(f"{'':<16}{name}: {_short(change.before.get(name))} -> {_short(value)}")
        print(f"\n{len(registry.entries)} registry entries, {len(sources)} sources; "
              f"{len(actionable)} change(s), {len(changes) - len(actionable)} unregistered")

        if not actionable:
            print("Nothing to apply.")
            return 0
        if not args.apply:
            print("Dry run: nothing changed. Re-run with --apply to make these changes.")
            return 0

        by_id = {s.id: s for s in sources}
        for change in actionable:
            if change.kind == "create":
                db.add(Source(**change.fields))
            else:
                source = by_id[change.source_id]
                for name, value in change.fields.items():
                    setattr(source, name, value)
        await db.commit()
        print(f"Applied {len(actionable)} change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
