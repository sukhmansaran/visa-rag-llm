"""
Policy watch (M7): check every official registry page for changes now, instead of waiting for the daily run.

    cd backend
    python scripts/policy_watch.py                # fetch all registry pages; analyse what changed
    python scripts/policy_watch.py --limit 5      # only the first 5 pages
    python scripts/policy_watch.py --no-model     # summaries written by code only (no Ollama needed)

A changed page is put in the review queue with an analysis: what changed, which ircc_rules.yaml keys held a figure
that is no longer on the page, and which stored chunks are affected. Nothing is changed in the rules or the
knowledge base; review the items with scripts/review_queue.py or on the admin page.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services import policy_watch  # noqa: E402


async def run(args) -> int:
    async with AsyncSessionLocal() as db:
        report = await policy_watch.sweep(db, limit=args.limit, use_model=not args.no_model)
    print(f"{report['pages']} registry pages: {report['fetched']} fetched, {len(report['failed'])} failed, "
          f"{len(report['analysed'])} change(s) analysed.")
    for failure in report["failed"]:
        print(f"  could not fetch {failure['url']}: {failure['reason']}")
    for item in report["analysed"]:
        rules = ", ".join(item["rules"]) or "none"
        print(f"  review item {item['id']} ({item['kind']}): {item['url']}\n    rules to check: {rules}")
    if report["analysed"]:
        print("Review them: python scripts/review_queue.py list")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check official pages for changes and queue them for review.")
    parser.add_argument("--limit", type=int, help="only the first N registry pages")
    parser.add_argument("--no-model", action="store_true", help="don't ask the model for a summary")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
