"""
Verify every page in the official source registry (M0.10). Never edits the registry or the KB; with --record
it saves each result's status and time on the matching source row.

    cd backend
    python scripts/verify_registry.py                 # all entries
    python scripts/verify_registry.py --id pgwp-about # one entry
    python scripts/verify_registry.py --json report.json
    python scripts/verify_registry.py --record        # also save status + time on each synced source

Each URL is fetched through the DNS-pinned client and must return HTTP 200, be allowed by robots.txt, stay on
the domain allowlist through redirects, and not be an error page served with HTTP 200 (a soft 404).
Exit code 1 if any entry fails.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.crawler.safe_http import pinned_client  # noqa: E402
from app.services.source_registry import REGISTRY_PATH, load_registry, verify_entry  # noqa: E402

DELAY_BETWEEN_REQUESTS_S = 1.0  # be polite to canada.ca
RETRY_AFTER_S = 5.0


async def record_results(results) -> None:
    """Store each result on the source with the same registry_id. Only these two columns are written."""
    from datetime import datetime

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.source import Source

    async with AsyncSessionLocal() as db:
        sources = {s.registry_id: s for s in (await db.execute(select(Source))).scalars() if s.registry_id}
        missing = []
        for result in results:
            source = sources.get(result.entry_id)
            if source is None:
                missing.append(result.entry_id)
                continue
            source.verify_status = result.status
            source.last_verified_at = datetime.fromisoformat(result.checked_at)
        await db.commit()
    print(f"Recorded {len(results) - len(missing)} result(s)"
          + (f"; not synced yet (run sync_sources.py): {', '.join(missing)}" if missing else ""))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--id", action="append", help="verify only these entry ids")
    parser.add_argument("--json", type=Path, help="also write the results as JSON")
    parser.add_argument("--record", action="store_true",
                        help="save verify_status and last_verified_at on sources (run sync_sources.py --apply first)")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    entries = [e for e in registry.entries if not args.id or e.id in args.id]
    results, robots_cache = [], {}
    async with pinned_client(timeout=30) as client:
        for i, entry in enumerate(entries):
            if i:
                await asyncio.sleep(DELAY_BETWEEN_REQUESTS_S)
            result = await verify_entry(client, entry, robots_cache)
            if result.status == "error":  # network blip (e.g. a dropped connection): one retry
                await asyncio.sleep(RETRY_AFTER_S)
                result = await verify_entry(client, entry, robots_cache)
            results.append(result)
            mark = "OK  " if result.ok else "FAIL"
            print(f"{mark} {result.status:<18} {result.main_text_chars:>6} chars  {entry.id}"
                  + (f"  -- {result.detail}" if result.detail else ""), flush=True)

    if args.record:
        await record_results(results)
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verified" + (f"; {len(failed)} failed" if failed else ""))
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        print(f"Results written to {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
