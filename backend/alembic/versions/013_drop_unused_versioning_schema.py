"""Drop the unused B2.2 versioning schema (M0.14b)

The IngestionOrchestrator that used these tables was removed in M0.14a (never wired in; its tables stayed
empty). Drops its 8 tables and the 3 vector_chunks columns that pointed into them. Keeps vector_chunks.status
(+ its check and index): the ingestion pipeline marks older versions' chunks 'superseded' with it.

Refuses to run if any of these tables has rows or any of the columns holds a value. The downgrade recreates the
schema with migration 010's own create_versioning_schema() (no backfill).

Revision ID: 013
Revises: 012
Create Date: 2026-10-20
"""
import importlib.util
from pathlib import Path

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None

# Children first (foreign keys)
TABLES = [
    'current_document_pointers', 'legacy_document_version_mappings', 'document_changes',
    'version_indexing_operations', 'migration_unmapped_records', 'document_versions', 'ingestion_runs',
    'logical_documents',
]
VECTOR_CHUNK_COLUMNS = ['document_version_id', 'logical_document_id', 'chunk_id']


def _exists(sql: str, **params) -> bool:
    return op.get_bind().execute(sa.text(sql), params).fetchone() is not None


def _table_exists(table: str) -> bool:
    return _exists("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t", t=table)


def _column_exists(table: str, column: str) -> bool:
    return _exists("SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                   "AND table_name=:t AND column_name=:c", t=table, c=column)


def _constraint_exists(table: str, name: str) -> bool:
    return _exists("SELECT 1 FROM information_schema.table_constraints WHERE table_schema='public' "
                   "AND table_name=:t AND constraint_name=:n", t=table, n=name)


def _index_exists(name: str) -> bool:
    return _exists("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:n", n=name)


def _refuse_if_used() -> None:
    conn = op.get_bind()
    used = []
    for table in TABLES:
        if _table_exists(table):
            rows = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
            if rows:
                used.append(f"{table}: {rows} row(s)")
    present = [c for c in VECTOR_CHUNK_COLUMNS if _column_exists('vector_chunks', c)]
    if present:
        filled = conn.execute(sa.text(
            "SELECT COUNT(*) FROM vector_chunks WHERE " + " OR ".join(f"{c} IS NOT NULL" for c in present)
        )).scalar() or 0
        if filled:
            used.append(f"vector_chunks: {filled} row(s) with versioning columns set")
    if used:
        raise RuntimeError("Refusing to drop the versioning schema, it holds data: " + "; ".join(used)
                           + ". Investigate before dropping anything.")


def upgrade() -> None:
    if not context.is_offline_mode():
        _refuse_if_used()

    for name in ('fk_vector_chunks_composite_doc_ver', 'chk_vector_chunks_paired_doc_ver', 'uq_vector_chunks_chunk_id'):
        if context.is_offline_mode() or _constraint_exists('vector_chunks', name):
            kind = {'fk': 'foreignkey', 'chk': 'check', 'uq': 'unique'}[name.split('_')[0]]
            op.drop_constraint(name, 'vector_chunks', type_=kind)
    if context.is_offline_mode() or _index_exists('ix_vector_chunks_version_id'):
        op.drop_index('ix_vector_chunks_version_id', table_name='vector_chunks')
    for column in VECTOR_CHUNK_COLUMNS:
        if context.is_offline_mode() or _column_exists('vector_chunks', column):
            op.drop_column('vector_chunks', column)

    for table in TABLES:
        if context.is_offline_mode() or _table_exists(table):
            op.drop_table(table)


def _migration_010():
    path = Path(__file__).with_name("010_immutable_versioning_and_ingestion_runs.py")
    spec = importlib.util.spec_from_file_location("migration_010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def downgrade() -> None:
    # Same tables, columns, constraints and indexes as migration 010 created (empty; no backfill)
    _migration_010().create_versioning_schema()
