"""
Remove a deactivated source's stored pages and chunks from the knowledge base (M0.10b).

    cd backend
    python scripts/remove_source_chunks.py --source-id 15            # dry run: show exactly what would go
    python scripts/remove_source_chunks.py --source-id 15 --apply    # back up, then remove

Run by the owner, never automatically. Rules:
  - only inactive sources (deactivate first: registry `excluded` + sync_sources.py --apply)
  - --apply backs up the database and chroma_data first (scripts/backup_now.py) and stops if that fails
  - removes the source's Chroma chunks, vector_chunks rows and documents; the source row stays (inactive) as a record
  - stops without changing anything if other tables still reference the documents (crawled pages, program
    records): those need a decision, not a cascade
Retrieval already ignores inactive sources, so this is cleanup, not a fix that answers depend on.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, text  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.models.vector_chunk import VectorChunk  # noqa: E402

# Tables that may reference documents and are NOT removed by this script
BLOCKING_REFERENCES = [
    ("crawled_pages", "document_id"),
    ("program_records", "document_id"),
]


async def plan(db, vector_store, source_id: int) -> dict:
    """What removing this source's content involves. Raises SystemExit with a reason if it must not proceed."""
    source = await db.get(Source, source_id)
    if source is None:
        raise SystemExit(f"Source {source_id} does not exist.")
    if source.is_active:
        raise SystemExit(f"Source {source_id} ({source.url}) is active. Deactivate it first "
                         "(add it to `excluded` in app/data/official_sources.yaml, then sync_sources.py --apply).")
    doc_ids = list((await db.execute(select(Document.id).where(Document.source_id == source_id))).scalars())
    chunk_rows = list((await db.execute(select(VectorChunk).where(VectorChunk.document_id.in_(doc_ids or [-1]))))
                      .scalars())
    chroma = await asyncio.to_thread(vector_store.collection.get, where={"source_id": source_id},
                                     include=["documents"])
    blockers = {}
    for table, column in BLOCKING_REFERENCES:
        if doc_ids:
            count = (await db.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = ANY(:ids)"),
                                      {"ids": doc_ids})).scalar()
            if count:
                blockers[table] = count
    doc_chars = dict((await db.execute(select(Document.id, func.length(Document.extracted_text))
                                       .where(Document.source_id == source_id))).all())
    return {"source": source, "doc_ids": doc_ids, "doc_chars": doc_chars, "chunk_rows": chunk_rows,
            "chroma_ids": chroma["ids"], "chroma_texts": chroma["documents"], "blockers": blockers}


async def remove(db, vector_store, plans) -> None:
    """Delete exactly what the plans list. Chroma first: a failure there leaves the database untouched."""
    from app.services.vector_store import _invalidate_answer_cache

    for p in plans:
        if p["blockers"]:
            raise RuntimeError(f"Source {p['source'].id} has blocking references: {p['blockers']}")
        if p["chroma_ids"]:
            await asyncio.to_thread(vector_store.collection.delete, ids=p["chroma_ids"])
        if p["doc_ids"]:
            await db.execute(delete(VectorChunk).where(VectorChunk.document_id.in_(p["doc_ids"])))
            await db.execute(delete(Document).where(Document.id.in_(p["doc_ids"])))
    await db.commit()
    _invalidate_answer_cache()


def show(p: dict) -> None:
    source = p["source"]
    print(f"Source {source.id}: {source.name}  {source.url}  (inactive, verify_status={source.verify_status})")
    docs = ", ".join(f"#{d} ({p['doc_chars'][d]} chars)" for d in p["doc_ids"])
    print(f"  documents:     {len(p['doc_ids'])}  {docs}")
    print(f"  vector_chunks: {len(p['chunk_rows'])} rows")
    print(f"  Chroma chunks: {len(p['chroma_ids'])}")
    for chunk_id, chunk_text in zip(p["chroma_ids"], p["chroma_texts"]):
        print(f"    {chunk_id}: {' '.join((chunk_text or '').split())[:100]}")
    row_ids = {c.vector_id for c in p["chunk_rows"]}
    if row_ids != set(p["chroma_ids"]):
        print(f"  note: vector_chunks and Chroma differ ({len(row_ids - set(p['chroma_ids']))} rows without a Chroma "
              f"chunk, {len(set(p['chroma_ids']) - row_ids)} Chroma chunks without a row); both are removed")
    if p["blockers"]:
        print("  BLOCKED: other tables reference these documents: "
              + ", ".join(f"{t} ({n})" for t, n in p["blockers"].items()))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="back up, then remove (default: dry run)")
    args = parser.parse_args()

    from app.services.vector_store import vector_store

    async with AsyncSessionLocal() as db:
        plans = [await plan(db, vector_store, sid) for sid in args.source_id]
        for p in plans:
            show(p)
        if any(p["blockers"] for p in plans):
            print("\nNothing changed: resolve the references above first.")
            return 1
        if not any(p["doc_ids"] or p["chroma_ids"] for p in plans):
            print("\nNothing to remove.")
            return 0
        if not args.apply:
            print("\nDry run: nothing changed. Re-run with --apply to back up and remove.")
            return 0

        from backup_now import backup
        dump_path, chroma_copy = backup("pre_remove_source_" + "_".join(map(str, args.source_id)))
        print(f"\nBacked up: {dump_path}\n           {chroma_copy}")

        await remove(db, vector_store, plans)

    removed = sum(len(p["chroma_ids"]) for p in plans)
    print(f"Removed {removed} Chroma chunk(s) and {sum(len(p['doc_ids']) for p in plans)} document(s). "
          "Restart the API so its answer cache is cleared too.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
