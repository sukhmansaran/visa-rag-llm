"""
Review queue for live-fetched pages (M5.5b, D2): what the agent fetched that differs from the stored copy.

    cd backend
    python scripts/review_queue.py list                 # pages waiting for review
    python scripts/review_queue.py list --status all    # also approved and rejected ones
    python scripts/review_queue.py show 3               # the diff against the stored copy
    python scripts/review_queue.py show 3 --text        # ... and the whole fetched text
    python scripts/review_queue.py approve 3            # back up, then store the reviewed text as the page's version
    python scripts/review_queue.py reject 3             # delete the fetched text; the knowledge base is unchanged

Run by the owner, never automatically. Approving backs up the database and chroma_data first
(scripts/backup_now.py) and changes nothing if that fails. The same actions are on the admin API
(/api/v1/admin/review-queue).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services import review_queue  # noqa: E402


async def run(args) -> int:
    async with AsyncSessionLocal() as db:
        try:
            if args.command == "list":
                items = await review_queue.list_items(db, None if args.status == "all" else args.status, 500)
                if not items:
                    print(f"No {'' if args.status == 'all' else args.status + ' '}items.")
                for item in items:
                    print(f"{item['id']:>4}  {item['status']:<9} {item['fetched_at'][:16]}  {item['chars']:>7} chars  "
                          f"{item['source_name']}\n      {item['url']}"
                          + (f"\n      {item['outcome']}" if item["outcome"] else ""))
            elif args.command == "show":
                item = await review_queue.detail(db, args.id)
                print(f"Item {item['id']} ({item['status']}): {item['source_name']}\n{item['url']}\n"
                      f"fetched {item['fetched_at']}, {item['chars']} chars; stored copy from "
                      f"{item['stored_scraped_at'] or 'none (never ingested)'}\n")
                print("\n".join(item["diff"]) or "(no diff: the item is reviewed, or the texts are identical)")
                if args.text:
                    print("\n----- fetched text -----\n" + item["text"])
            elif args.command == "approve":
                item = await review_queue.approve(db, args.id)
                print(f"Approved item {item['id']}: {item['outcome']}")
            elif args.command == "reject":
                item = await review_queue.reject(db, args.id)
                print(f"Rejected item {item['id']}: {item['outcome']}")
        except review_queue.ReviewError as e:
            print(f"Refused: {e}")
            return 1
        finally:
            from app.services.answer_jobs import close_redis

            await close_redis()  # rejecting drops the cached copy through a connection bound to this event loop
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # page text on a Windows console
    parser = argparse.ArgumentParser(description="Review live-fetched pages before they enter the knowledge base.")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--status", default="pending", choices=["pending", "approved", "rejected", "all"])
    show = commands.add_parser("show")
    show.add_argument("id", type=int)
    show.add_argument("--text", action="store_true", help="also print the whole fetched text")
    for name in ("approve", "reject"):
        commands.add_parser(name).add_argument("id", type=int)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
