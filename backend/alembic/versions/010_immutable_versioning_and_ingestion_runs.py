"""Immutable document versioning, current pointers, and legacy backfill

Revision ID: 010
Revises: 009
Create Date: 2026-10-09 22:15:00

"""
import hashlib
import os
from urllib.parse import urlparse, urlunparse
from alembic import op, context
import sqlalchemy as sa


revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None

DISPOSABLE_DATABASE_ALLOWLIST = {
    "visa_chatbot_test",
    "visa_chatbot_ci_test",
    "visa_chatbot_migration_test",
    "visa_chatbot_disposable_migration_test",
}


def _is_offline() -> bool:
    return context.is_offline_mode()


def _get_current_dbname() -> str:
    if _is_offline():
        return "offline"
    conn = op.get_bind()
    res = conn.execute(sa.text("SELECT current_database()")).scalar()
    return str(res or "").strip()


def _table_exists(table: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"
    ), {"t": table})
    return result is not None and result.fetchone() is not None


def _column_exists(table: str, column: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
    ), {"t": table, "c": column})
    return result is not None and result.fetchone() is not None


def _constraint_exists(table: str, constraint: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE table_schema='public' AND table_name=:t AND constraint_name=:c"
    ), {"t": table, "c": constraint})
    return result is not None and result.fetchone() is not None


def _index_exists(index_name: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:i"
    ), {"i": index_name})
    return result is not None and result.fetchone() is not None


def normalize_url(raw_url: str) -> str:
    """Deterministic RFC 3986 normalization preserving semantic parameters."""
    if not raw_url:
        return ""
    parsed = urlparse(raw_url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    
    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
        
    query_parts = []
    if parsed.query:
        for q in parsed.query.split("&"):
            if not q:
                continue
            k = q.split("=")[0].lower()
            if not (k.startswith("utm_") or k in {"fbclid", "gclid", "_ga", "ref", "source"}):
                query_parts.append(q)
    query_parts.sort()
    norm_query = "&".join(query_parts)
    
    return urlunparse((scheme, netloc, path, "", norm_query, ""))


def upgrade() -> None:
    # 1. Create logical_documents
    if not _table_exists('logical_documents'):
        op.create_table(
            'logical_documents',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('document_key', sa.String(length=64), nullable=False),
            sa.Column('primary_url', sa.String(length=2048), nullable=False),
            sa.Column('canonical_url', sa.String(length=2048), nullable=True),
            sa.Column('title', sa.String(length=512), nullable=False),
            sa.Column('document_type', sa.String(length=50), nullable=False, server_default='policy_guide'),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='active'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_failure_category', sa.String(length=50), nullable=True),
            sa.Column('last_failure_http_status', sa.Integer(), nullable=True),
            sa.CheckConstraint("status IN ('active', 'unavailable', 'archived')", name='chk_logical_doc_status'),
            sa.CheckConstraint("document_type IN ('policy_guide', 'regulation', 'dli_list', 'draw_schedule', 'fee_schedule', 'system_archive')", name='chk_logical_doc_type'),
        )
        op.create_unique_constraint('uq_logical_docs_key', 'logical_documents', ['document_key'])
        op.create_index('ix_logical_docs_source', 'logical_documents', ['source_id'])
        op.create_index('ix_logical_docs_status', 'logical_documents', ['status'])

    # 2. Create ingestion_runs
    if not _table_exists('ingestion_runs'):
        op.create_table(
            'ingestion_runs',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('run_id', sa.String(length=64), unique=True, nullable=False),
            sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id', ondelete='SET NULL'), nullable=True),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='started'),
            sa.Column('trigger_type', sa.String(length=30), nullable=False, server_default='manual'),
            sa.Column('documents_fetched', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('documents_updated', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('documents_unchanged', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('documents_failed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('error_summary', sa.Text(), nullable=True),
            sa.Column('run_metadata', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('started', 'completed', 'failed', 'partial')", name='chk_ingestion_run_status'),
        )
        op.create_index('ix_ingestion_runs_run_id', 'ingestion_runs', ['run_id'])
        op.create_index('ix_ingestion_runs_source_id', 'ingestion_runs', ['source_id'])
        op.create_index('ix_ingestion_runs_status', 'ingestion_runs', ['status'])

    # 3. Create document_versions
    if not _table_exists('document_versions'):
        op.create_table(
            'document_versions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('logical_document_id', sa.Integer(), sa.ForeignKey('logical_documents.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('ingestion_run_id', sa.Integer(), sa.ForeignKey('ingestion_runs.id', ondelete='SET NULL'), nullable=True),
            sa.Column('version_number', sa.Integer(), nullable=False),
            sa.Column('lifecycle_state', sa.String(length=30), nullable=False, server_default='fetched'),
            sa.Column('requested_url', sa.String(length=2048), nullable=False),
            sa.Column('final_url', sa.String(length=2048), nullable=False),
            sa.Column('raw_content_hash', sa.String(length=64), nullable=True),
            sa.Column('normalized_content_hash', sa.String(length=64), nullable=True),
            sa.Column('legacy_scraper_hash', sa.String(length=64), nullable=True),
            sa.Column('etag', sa.String(length=255), nullable=True),
            sa.Column('last_modified', sa.String(length=255), nullable=True),
            sa.Column('content_type', sa.String(length=100), nullable=False, server_default='text/html'),
            sa.Column('raw_byte_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('normalized_char_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('language', sa.String(length=20), nullable=True, server_default='en'),
            sa.Column('published_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('effective_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('extracted_text', sa.Text(), nullable=False),
            sa.Column('raw_html', sa.Text(), nullable=True),
            sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("lifecycle_state IN ('fetched', 'validated', 'indexing', 'ready', 'failed', 'superseded')", name='chk_doc_ver_lifecycle'),
            sa.CheckConstraint("raw_byte_count >= 0", name='chk_doc_ver_byte_count'),
            sa.CheckConstraint("normalized_char_count >= 0", name='chk_doc_ver_char_count'),
        )
        op.create_unique_constraint('uq_doc_ver_sequence', 'document_versions', ['logical_document_id', 'version_number'])
        op.create_unique_constraint('uq_doc_ver_composite_id', 'document_versions', ['logical_document_id', 'id'])
        op.create_index('ix_doc_ver_logical_doc', 'document_versions', ['logical_document_id'])
        op.create_index('ix_doc_ver_ingestion_run', 'document_versions', ['ingestion_run_id'])
        op.create_index('ix_doc_ver_norm_hash', 'document_versions', ['normalized_content_hash'])
        op.create_index('ix_doc_ver_lifecycle', 'document_versions', ['lifecycle_state'])

    # 3. Create current_document_pointers
    if not _table_exists('current_document_pointers'):
        op.create_table(
            'current_document_pointers',
            sa.Column('logical_document_id', sa.Integer(), sa.ForeignKey('logical_documents.id', ondelete='CASCADE'), primary_key=True, nullable=False),
            sa.Column('current_version_id', sa.Integer(), nullable=False),
            sa.Column('promoted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('promoted_by', sa.String(length=100), nullable=False, server_default='ingestion_pipeline'),
            sa.Column('verified_chunk_count', sa.Integer(), nullable=False, server_default='0'),
            sa.UniqueConstraint('current_version_id', name='uq_current_pointers_ver'),
            sa.ForeignKeyConstraint(
                ['logical_document_id', 'current_version_id'],
                ['document_versions.logical_document_id', 'document_versions.id'],
                name='fk_pointer_matching_doc_version',
                ondelete='RESTRICT',
            ),
            sa.CheckConstraint('verified_chunk_count >= 0', name='chk_pointer_chunk_count'),
        )

    # 4. Create legacy_document_version_mappings
    if not _table_exists('legacy_document_version_mappings'):
        op.create_table(
            'legacy_document_version_mappings',
            sa.Column('legacy_document_id', sa.Integer(), sa.ForeignKey('documents.id', ondelete='RESTRICT'), primary_key=True, nullable=False),
            sa.Column('logical_document_id', sa.Integer(), nullable=False),
            sa.Column('document_version_id', sa.Integer(), nullable=False),
            sa.Column('is_deduplicated', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('mapped_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ['logical_document_id', 'document_version_id'],
                ['document_versions.logical_document_id', 'document_versions.id'],
                name='fk_legacy_map_composite_doc_ver',
                ondelete='RESTRICT',
            ),
        )
        op.create_index('ix_legacy_map_ver', 'legacy_document_version_mappings', ['document_version_id'])
        op.create_index('ix_legacy_map_doc', 'legacy_document_version_mappings', ['logical_document_id'])

    # 5. Create version_indexing_operations
    if not _table_exists('version_indexing_operations'):
        op.create_table(
            'version_indexing_operations',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('document_version_id', sa.Integer(), nullable=False),
            sa.Column('logical_document_id', sa.Integer(), nullable=False),
            sa.Column('operation_type', sa.String(length=30), nullable=False, server_default='index_new_version'),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
            sa.Column('target_chunk_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('verified_chunk_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('vector_backend', sa.String(length=30), nullable=False, server_default='chroma'),
            sa.Column('worker_lease_id', sa.String(length=100), nullable=True),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('retry_count', sa.SmallInteger(), nullable=False, server_default='0'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ['logical_document_id', 'document_version_id'],
                ['document_versions.logical_document_id', 'document_versions.id'],
                name='fk_indexing_op_composite_doc_ver',
                ondelete='RESTRICT',
            ),
            sa.CheckConstraint("operation_type IN ('index_new_version', 'cleanup_superseded_version')", name='chk_indexing_op_type'),
            sa.CheckConstraint("status IN ('pending', 'in_progress', 'verified', 'failed', 'completed')", name='chk_indexing_op_status'),
            sa.CheckConstraint("vector_backend IN ('chroma', 'pinecone')", name='chk_indexing_op_backend'),
        )
        op.create_index('ix_indexing_op_ver', 'version_indexing_operations', ['document_version_id'])
        op.create_index('ix_indexing_op_status', 'version_indexing_operations', ['status'])

    # 6. Create document_changes
    if not _table_exists('document_changes'):
        op.create_table(
            'document_changes',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('logical_document_id', sa.Integer(), nullable=False),
            sa.Column('old_version_id', sa.Integer(), nullable=True),
            sa.Column('new_version_id', sa.Integer(), nullable=False),
            sa.Column('change_type', sa.String(length=50), nullable=False),
            sa.Column('severity', sa.String(length=20), nullable=False, server_default='medium'),
            sa.Column('review_status', sa.String(length=30), nullable=False, server_default='auto_approved'),
            sa.Column('requires_notification', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('diff_patch', sa.JSON(), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('logical_document_id', 'new_version_id', name='uq_doc_change_pair'),
            sa.ForeignKeyConstraint(
                ['logical_document_id', 'new_version_id'],
                ['document_versions.logical_document_id', 'document_versions.id'],
                name='fk_doc_change_new_composite_ver',
                ondelete='RESTRICT',
            ),
            sa.ForeignKeyConstraint(
                ['logical_document_id', 'old_version_id'],
                ['document_versions.logical_document_id', 'document_versions.id'],
                name='fk_doc_change_old_composite_ver',
                ondelete='RESTRICT',
            ),
            sa.CheckConstraint("change_type IN ('threshold_update', 'intake_status', 'statutory', 'procedural', 'wording', 'initial_version')", name='chk_doc_change_type'),
            sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name='chk_doc_change_severity'),
            sa.CheckConstraint("review_status IN ('auto_approved', 'review_required', 'reviewed')", name='chk_doc_change_review'),
        )
        op.create_index('ix_doc_changes_logical', 'document_changes', ['logical_document_id'])
        op.create_index('ix_doc_changes_severity', 'document_changes', ['severity'])

    # 7. Create migration_unmapped_records
    if not _table_exists('migration_unmapped_records'):
        op.create_table(
            'migration_unmapped_records',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('legacy_table', sa.String(length=50), nullable=False),
            sa.Column('legacy_record_id', sa.Integer(), nullable=False),
            sa.Column('issue_category', sa.String(length=50), nullable=False),
            sa.Column('raw_payload_snippet', sa.Text(), nullable=True),
            sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('resolved', sa.Boolean(), nullable=False, server_default='false'),
            sa.UniqueConstraint('legacy_table', 'legacy_record_id', 'issue_category', name='uq_unmapped_record'),
            sa.CheckConstraint("legacy_table IN ('documents', 'vector_chunks')", name='chk_unmapped_table'),
            sa.CheckConstraint("issue_category IN ('missing_source', 'empty_content', 'orphaned_chunk')", name='chk_unmapped_issue'),
        )

    # 8. Extend vector_chunks
    if not _column_exists('vector_chunks', 'document_version_id'):
        op.add_column('vector_chunks', sa.Column('document_version_id', sa.Integer(), nullable=True))
    if not _column_exists('vector_chunks', 'logical_document_id'):
        op.add_column('vector_chunks', sa.Column('logical_document_id', sa.Integer(), nullable=True))
    if not _column_exists('vector_chunks', 'chunk_id'):
        op.add_column('vector_chunks', sa.Column('chunk_id', sa.String(length=255), nullable=True))
    if not _column_exists('vector_chunks', 'status'):
        op.add_column('vector_chunks', sa.Column('status', sa.String(length=20), nullable=False, server_default='active'))

    if not _constraint_exists('vector_chunks', 'uq_vector_chunks_chunk_id'):
        op.create_unique_constraint('uq_vector_chunks_chunk_id', 'vector_chunks', ['chunk_id'])
    if not _constraint_exists('vector_chunks', 'chk_vector_chunk_status'):
        op.create_check_constraint(
            'chk_vector_chunk_status',
            'vector_chunks',
            "status IN ('staging', 'active', 'superseded', 'tombstoned')",
        )
    if not _constraint_exists('vector_chunks', 'chk_vector_chunks_paired_doc_ver'):
        op.create_check_constraint(
            'chk_vector_chunks_paired_doc_ver',
            'vector_chunks',
            "((document_version_id IS NULL AND logical_document_id IS NULL) OR (document_version_id IS NOT NULL AND logical_document_id IS NOT NULL))",
        )
    if not _constraint_exists('vector_chunks', 'fk_vector_chunks_composite_doc_ver'):
        op.create_foreign_key(
            'fk_vector_chunks_composite_doc_ver',
            'vector_chunks',
            'document_versions',
            ['logical_document_id', 'document_version_id'],
            ['logical_document_id', 'id'],
            ondelete='RESTRICT',
        )

    if not _index_exists('ix_vector_chunks_version_id'):
        op.create_index('ix_vector_chunks_version_id', 'vector_chunks', ['document_version_id'])
    if not _index_exists('ix_vector_chunks_status'):
        op.create_index('ix_vector_chunks_status', 'vector_chunks', ['status'])

    # 9. Execute Deterministic Legacy Backfill (if online and legacy documents exist)
    if not _is_offline():
        _execute_backfill_migration()


def _execute_backfill_migration() -> None:
    """Execute deterministic, batch-safe legacy backfill within migration transaction."""
    conn = op.get_bind()

    # Step 1: Ensure system origin row exists
    res = conn.execute(sa.text("""
        INSERT INTO sources (url, name, source_type, priority, authority_tier, scrape_frequency, is_active, created_at)
        VALUES ('system://legacy-unmapped-import', 'System Unmapped Archive', 'system_archive', 5, 4, 8760, false, now())
        ON CONFLICT (url) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """)).scalar()
    sys_source_id = int(res)

    # Step 2: Batch by distinct target URLs
    batch_size = 500
    while True:
        url_batch = conn.execute(sa.text("""
            SELECT DISTINCT COALESCE(
                (SELECT cp.url FROM crawled_pages cp WHERE cp.document_id = d.id ORDER BY cp.id DESC LIMIT 1),
                s.url,
                'legacy-orphan://document/' || d.id
            ) AS raw_url
            FROM documents d
            LEFT JOIN sources s ON s.id = d.source_id
            WHERE d.id NOT IN (SELECT legacy_document_id FROM legacy_document_version_mappings)
            ORDER BY raw_url ASC
            LIMIT :b
        """), {"b": batch_size}).scalars().all()

        if not url_batch:
            break

        for raw_url in url_batch:
            norm_url = normalize_url(raw_url) if not raw_url.startswith("legacy-orphan://") else raw_url
            doc_key = hashlib.sha256(norm_url.encode("utf-8")).hexdigest()

            # Find matching legacy documents in strict chronological order
            doc_rows = conn.execute(sa.text("""
                SELECT d.id AS doc_id, d.source_id, d.content_hash, d.raw_html, d.extracted_text, d.scraped_at,
                       s.id AS matched_source_id, s.authority_tier AS source_tier
                FROM documents d
                LEFT JOIN sources s ON s.id = d.source_id
                WHERE COALESCE(
                    (SELECT cp.url FROM crawled_pages cp WHERE cp.document_id = d.id ORDER BY cp.id DESC LIMIT 1),
                    s.url,
                    'legacy-orphan://document/' || d.id
                ) = :u
                  AND d.id NOT IN (SELECT legacy_document_id FROM legacy_document_version_mappings)
                ORDER BY d.scraped_at ASC NULLS FIRST, d.id ASC
            """), {"u": raw_url}).mappings().all()

            if not doc_rows:
                continue

            first_row = doc_rows[0]
            target_source_id = first_row["matched_source_id"] or sys_source_id

            # Upsert logical document
            log_doc_id = conn.execute(sa.text("""
                INSERT INTO logical_documents (source_id, document_key, primary_url, title, status, created_at, updated_at)
                VALUES (:sid, :k, :u, :t, 'active', COALESCE(:scraped, now()), now())
                ON CONFLICT (document_key) DO UPDATE SET updated_at = now()
                RETURNING id
            """), {
                "sid": target_source_id,
                "k": doc_key,
                "u": norm_url,
                "t": f"Migrated: {norm_url}",
                "scraped": first_row["scraped_at"],
            }).scalar()

            # Process historical snapshots for this URL
            for r in doc_rows:
                clean_text = (r["extracted_text"] or "").strip()
                is_valid = len(clean_text) >= 20
                raw_bytes = len(r["raw_html"].encode("utf-8")) if r["raw_html"] else 0
                char_count = len(clean_text)
                scraped_ts = r["scraped_at"]

                # Deduplication check against previous version
                last_ver = conn.execute(sa.text("""
                    SELECT id, version_number, legacy_scraper_hash, extracted_text
                    FROM document_versions
                    WHERE logical_document_id = :lid
                    ORDER BY version_number DESC LIMIT 1
                """), {"lid": log_doc_id}).mappings().first()

                if last_ver and last_ver["legacy_scraper_hash"] == r["content_hash"] and last_ver["extracted_text"] == clean_text:
                    # Collapsed identical snapshot
                    conn.execute(sa.text("""
                        INSERT INTO legacy_document_version_mappings (legacy_document_id, logical_document_id, document_version_id, is_deduplicated, mapped_at)
                        VALUES (:did, :lid, :vid, true, now())
                    """), {"did": r["doc_id"], "lid": log_doc_id, "vid": last_ver["id"]})
                else:
                    next_ver = (last_ver["version_number"] + 1) if last_ver else 1
                    ver_state = 'superseded' if is_valid else 'failed'
                    vid = conn.execute(sa.text("""
                        INSERT INTO document_versions (
                            logical_document_id, version_number, lifecycle_state, requested_url, final_url,
                            legacy_scraper_hash, raw_byte_count, normalized_char_count, extracted_text,
                            raw_html, retrieved_at, created_at
                        ) VALUES (
                            :lid, :vnum, :state, :u, :u,
                            :hash, :bytes, :chars, :txt,
                            :html, COALESCE(:ts, now()), now()
                        ) RETURNING id
                    """), {
                        "lid": log_doc_id, "vnum": next_ver, "state": ver_state, "u": norm_url,
                        "hash": r["content_hash"], "bytes": raw_bytes, "chars": char_count,
                        "txt": clean_text, "html": r["raw_html"], "ts": scraped_ts
                    }).scalar()

                    conn.execute(sa.text("""
                        INSERT INTO legacy_document_version_mappings (legacy_document_id, logical_document_id, document_version_id, is_deduplicated, mapped_at)
                        VALUES (:did, :lid, :vid, false, now())
                    """), {"did": r["doc_id"], "lid": log_doc_id, "vid": vid})

                if not is_valid:
                    conn.execute(sa.text("""
                        INSERT INTO migration_unmapped_records (legacy_table, legacy_record_id, issue_category, raw_payload_snippet, detected_at)
                        VALUES ('documents', :did, 'empty_content', :snippet, now())
                        ON CONFLICT DO NOTHING
                    """), {"did": r["doc_id"], "snippet": clean_text[:200]})

            # Pointer promotion for this logical document
            cand_ver = conn.execute(sa.text("""
                SELECT id FROM document_versions
                WHERE logical_document_id = :lid AND lifecycle_state != 'failed'
                ORDER BY version_number DESC LIMIT 1
            """), {"lid": log_doc_id}).scalar()

            if cand_ver:
                conn.execute(sa.text("""
                    UPDATE document_versions SET lifecycle_state = 'ready' WHERE id = :vid
                """), {"vid": cand_ver})
                conn.execute(sa.text("""
                    INSERT INTO current_document_pointers (logical_document_id, current_version_id, promoted_at, promoted_by)
                    VALUES (:lid, :vid, now(), 'migration_010_backfill')
                    ON CONFLICT (logical_document_id) DO UPDATE
                    SET current_version_id = EXCLUDED.current_version_id, promoted_at = now()
                """), {"lid": log_doc_id, "vid": cand_ver})
            else:
                conn.execute(sa.text("""
                    UPDATE logical_documents SET status = 'unavailable' WHERE id = :lid
                """), {"lid": log_doc_id})

    # Step 3: Map legacy vector_chunks
    conn.execute(sa.text("""
        UPDATE vector_chunks vc
        SET document_version_id = m.document_version_id,
            logical_document_id = m.logical_document_id,
            chunk_id = 'legacy_c' || vc.id || '_d' || m.legacy_document_id || '_v' || m.document_version_id,
            status = CASE
                WHEN p.current_version_id = m.document_version_id THEN 'active'
                ELSE 'superseded'
            END
        FROM legacy_document_version_mappings m
        LEFT JOIN current_document_pointers p ON p.logical_document_id = m.logical_document_id
        WHERE vc.document_id = m.legacy_document_id
    """))

    # Step 4: Quarantine orphan vector chunks
    conn.execute(sa.text("""
        INSERT INTO migration_unmapped_records (legacy_table, legacy_record_id, issue_category, raw_payload_snippet, detected_at)
        SELECT 'vector_chunks', vc.id, 'orphaned_chunk', SUBSTRING(vc.text FROM 1 FOR 200), now()
        FROM vector_chunks vc
        WHERE vc.document_version_id IS NULL
        ON CONFLICT DO NOTHING
    """))

    # Step 5: Set-based Exhaustive Accounting Assertion
    unaccounted = conn.execute(sa.text("""
        SELECT id FROM vector_chunks
        EXCEPT
        (
            SELECT id FROM vector_chunks WHERE document_version_id IS NOT NULL
            UNION ALL
            SELECT legacy_record_id FROM migration_unmapped_records WHERE legacy_table = 'vector_chunks'
        )
    """)).scalars().all()

    if unaccounted:
        raise RuntimeError(f"FATAL: Backfill reconciliation failed. Found {len(unaccounted)} unaccounted chunks: {unaccounted[:5]}")


def downgrade() -> None:
    if _is_offline():
        _execute_downgrade_ddl()
        return

    dbname = _get_current_dbname()
    conn = op.get_bind()

    # 1. Fail-closed security guard: strictly reject downgrade on non-allowlisted databases
    if dbname not in DISPOSABLE_DATABASE_ALLOWLIST:
        raise RuntimeError(
            f"FATAL SECURITY VIOLATION: Refusing downgrade on database '{dbname}'. "
            f"Destructive downgrade is exclusively permitted on disposable test databases: "
            f"{sorted(DISPOSABLE_DATABASE_ALLOWLIST)}"
        )

    # 2. Check for active data that would be permanently destroyed
    counts = {}
    for tbl in [
        'current_document_pointers', 'legacy_document_version_mappings',
        'document_changes', 'version_indexing_operations',
        'document_versions', 'ingestion_runs', 'logical_documents', 'migration_unmapped_records'
    ]:
        if _table_exists(tbl):
            counts[tbl] = conn.execute(sa.text(f"SELECT COUNT(*) FROM {tbl}")).scalar() or 0
        else:
            counts[tbl] = 0

    total_records = sum(counts.values())
    allow_data_loss = os.environ.get("ALEMBIC_FORCE_DATA_LOSS", "").lower() == "true"

    if total_records > 0 and not allow_data_loss:
        summary_str = ", ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)
        raise RuntimeError(
            f"REFUSING DESTRUCTIVE DOWNGRADE: Migration 010 contains active data that would be permanently lost: "
            f"[{summary_str}]. To force destructive wipe on disposable test fixture, set ALEMBIC_FORCE_DATA_LOSS=true."
        )

    _execute_downgrade_ddl()


def _execute_downgrade_ddl() -> None:
    """Execute clean reverse DDL."""
    if _constraint_exists('vector_chunks', 'fk_vector_chunks_composite_doc_ver'):
        op.drop_constraint('fk_vector_chunks_composite_doc_ver', 'vector_chunks', type_='foreignkey')
    if _constraint_exists('vector_chunks', 'chk_vector_chunks_paired_doc_ver'):
        op.drop_constraint('chk_vector_chunks_paired_doc_ver', 'vector_chunks', type_='check')
    if _constraint_exists('vector_chunks', 'chk_vector_chunk_status'):
        op.drop_constraint('chk_vector_chunk_status', 'vector_chunks', type_='check')
    if _constraint_exists('vector_chunks', 'uq_vector_chunks_chunk_id'):
        op.drop_constraint('uq_vector_chunks_chunk_id', 'vector_chunks', type_='unique')

    if _index_exists('ix_vector_chunks_status'):
        op.drop_index('ix_vector_chunks_status', table_name='vector_chunks')
    if _index_exists('ix_vector_chunks_version_id'):
        op.drop_index('ix_vector_chunks_version_id', table_name='vector_chunks')

    if _column_exists('vector_chunks', 'status'):
        op.drop_column('vector_chunks', 'status')
    if _column_exists('vector_chunks', 'chunk_id'):
        op.drop_column('vector_chunks', 'chunk_id')
    if _column_exists('vector_chunks', 'logical_document_id'):
        op.drop_column('vector_chunks', 'logical_document_id')
    if _column_exists('vector_chunks', 'document_version_id'):
        op.drop_column('vector_chunks', 'document_version_id')

    # Drop tables in strict reverse-dependency order
    op.drop_table('migration_unmapped_records')
    op.drop_table('document_changes')
    op.drop_table('version_indexing_operations')
    op.drop_table('legacy_document_version_mappings')
    op.drop_table('current_document_pointers')
    op.drop_table('document_versions')
    op.drop_table('ingestion_runs')
    op.drop_table('logical_documents')
