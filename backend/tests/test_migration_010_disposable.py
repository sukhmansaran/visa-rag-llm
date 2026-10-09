"""
Disposable Database Test Suite for Alembic Migration 010 and B2.1 Data Models.

Target Database: visa_chatbot_disposable_migration_test
Safety Boundary: visa_chatbot development database remains strictly untouched at revision 008.

Acceptance Criteria Tested:
1. Deterministic legacy backfill (sequential versioning, chronological order, deduplication, null timestamps).
2. Set-based exhaustive chunk reconciliation (disjoint mapped/quarantined, zero unaccounted chunks).
3. Downgrade safety guard & database target protection (fail-closed on populated data and non-allowlist DBs).
4. Composite Foreign Key & Cross-Document Pointer Rejection (physical impossibility of mismatched doc/version).
5. Vector chunk paired nullability and lifecycle status constraints.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text, pool, inspect
from sqlalchemy.exc import IntegrityError, DBAPIError
from alembic.config import Config
from alembic import command

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
import app.models  # Ensure all models are imported and registered
from sqlmodel import SQLModel


DISPOSABLE_DB = "visa_chatbot_disposable_migration_test"


def get_connection_info():
    base_url = str(settings.DATABASE_URL).replace("+asyncpg", "")
    prefix, db_name = base_url.rsplit("/", 1)
    q = ""
    if "?" in db_name:
        _, q = db_name.split("?", 1)
        q = f"?{q}"
    maint_url = f"{prefix}/postgres{q}"
    disp_url = f"{prefix}/{DISPOSABLE_DB}{q}"
    dev_url = f"{prefix}/visa_chatbot{q}"
    return maint_url, disp_url, dev_url


MAINT_URL, DISP_URL, DEV_URL = get_connection_info()


def get_alembic_config(db_url):
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _verify_dev_db_revision(conn):
    """Verify that the connected development database contains valid Alembic metadata at revision 008."""
    # 1. Check alembic_version table exists
    tbl_exists = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'alembic_version'"
    )).scalar()
    if not tbl_exists:
        raise RuntimeError("CRITICAL SAFETY VIOLATION: visa_chatbot exists but alembic_version table is missing!")

    # 2. Check alembic_version has valid row
    rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
    if not rev:
        raise RuntimeError("CRITICAL SAFETY VIOLATION: visa_chatbot has empty or invalid alembic_version metadata!")

    assert rev == "008", f"CRITICAL SAFETY VIOLATION: visa_chatbot is at revision {rev}, expected 008!"


def assert_dev_db_untouched():
    """
    Assert that the real development database remains strictly at revision 008 if present,
    or confirmed absent in CI environments.
    
    Fail-closed policy:
    1. Confirm existence through a reliable connection to the PostgreSQL maintenance database.
    2. If the maintenance database is unavailable, fail closed unless an explicitly supported fallback
       (direct probe returning 3D000) can safely establish database absence.
    3. If visa_chatbot is confirmed absent, verify that it remains absent (cannot connect).
    4. If visa_chatbot is present, connect and verify:
       - alembic_version table exists.
       - exactly revision '008' is recorded.
    5. Unexpected connection failures, missing tables, or invalid metadata must fail the check.
    """
    from sqlalchemy.exc import OperationalError, DBAPIError

    maint_connected = False
    dev_exists = None
    maint_err = None

    try:
        maint_engine = create_engine(MAINT_URL, poolclass=pool.NullPool)
        with maint_engine.connect() as conn:
            maint_connected = True
            dev_exists = bool(conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'visa_chatbot'")
            ).scalar())
    except Exception as e:
        maint_err = e

    if not maint_connected:
        # Maintenance database is unavailable.
        # Fall back to direct probe ONLY to check if visa_chatbot is absent (code 3D000)
        # or cleanly present and at revision 008. Any other connection failure fails closed.
        try:
            dev_engine = create_engine(DEV_URL, poolclass=pool.NullPool)
            with dev_engine.connect() as conn:
                _verify_dev_db_revision(conn)
                return
        except (OperationalError, DBAPIError) as err:
            err_msg = str(err).lower()
            pgcode = getattr(getattr(err, "orig", None), "pgcode", None)
            if pgcode == "3D000" or 'database "visa_chatbot" does not exist' in err_msg:
                # Confirmed absent via PostgreSQL catalog error
                return
            raise RuntimeError(
                f"FAIL-CLOSED: Maintenance DB unavailable ({maint_err}) and direct connection failed: {err}"
            ) from err
        except Exception as err:
            raise RuntimeError(
                f"FAIL-CLOSED: Maintenance DB unavailable ({maint_err}) and direct check failed: {err}"
            ) from err

    # Maintenance database was reachable:
    if not dev_exists:
        # Confirmed absent via pg_database (e.g. CI runner).
        # Verify it remains absent by probing DEV_URL — connection MUST fail with 3D000 / does not exist.
        try:
            dev_engine = create_engine(DEV_URL, poolclass=pool.NullPool)
            with dev_engine.connect() as conn:
                raise RuntimeError(
                    "CRITICAL SAFETY VIOLATION: visa_chatbot was reported absent by pg_database "
                    "but direct connection succeeded! Database state is inconsistent."
                )
        except (OperationalError, DBAPIError) as err:
            err_msg = str(err).lower()
            pgcode = getattr(getattr(err, "orig", None), "pgcode", None)
            if pgcode == "3D000" or 'database "visa_chatbot" does not exist' in err_msg:
                # Confirmed absent from both maintenance catalog and direct connection probe
                return
            raise RuntimeError(
                f"FAIL-CLOSED: Confirmed absent in pg_database, but direct connection probe failed unexpectedly: {err}"
            ) from err

    # dev_exists is True: visa_chatbot is present on the server
    try:
        dev_engine = create_engine(DEV_URL, poolclass=pool.NullPool)
        with dev_engine.connect() as conn:
            _verify_dev_db_revision(conn)
    except (AssertionError, RuntimeError):
        raise
    except Exception as err:
        raise RuntimeError(
            f"FAIL-CLOSED: visa_chatbot exists in pg_database but connection failed: {err}"
        ) from err


def recreate_disposable_db():
    """Recreate the isolated disposable test database."""
    assert DISPOSABLE_DB != "visa_chatbot", "Safety check failed: cannot target visa_chatbot"
    maint_engine = create_engine(MAINT_URL, isolation_level="AUTOCOMMIT")
    with maint_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DISPOSABLE_DB} WITH (FORCE);"))
        conn.execute(text(f"CREATE DATABASE {DISPOSABLE_DB};"))


class TestMilestoneB21MigrationAndModels(unittest.TestCase):
    """Milestone B2.1 verification test suite running on disposable PostgreSQL fixture."""

    @classmethod
    def setUpClass(cls):
        # 1. Verify development database is untouched at 008 before tests
        assert_dev_db_untouched()

    @classmethod
    def tearDownClass(cls):
        # 1. Clean up disposable test database
        try:
            maint_engine = create_engine(MAINT_URL, isolation_level="AUTOCOMMIT")
            with maint_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {DISPOSABLE_DB} WITH (FORCE);"))
        except Exception:
            pass
        # 2. Re-verify development database is still untouched at 008 after tests
        assert_dev_db_untouched()

    def setUp(self):
        # Ensure dev database is untouched before each test
        assert_dev_db_untouched()

    def tearDown(self):
        # Ensure dev database is untouched after each test
        assert_dev_db_untouched()

    def test_01_clean_lifecycle_and_schema_reflection(self):
        """Verify clean upgrade base -> 008 -> 009 -> 010 and reflection of all tables."""
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)

        # Apply migrations up to head (010)
        command.upgrade(cfg, "head")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            self.assertEqual(rev, "010")

            inspector = inspect(engine)
            tables = set(inspector.get_table_names())

            required_tables = {
                "logical_documents",
                "ingestion_runs",
                "document_versions",
                "current_document_pointers",
                "legacy_document_version_mappings",
                "version_indexing_operations",
                "document_changes",
                "migration_unmapped_records",
                "sources",
                "documents",
                "vector_chunks",
            }
            for tbl in required_tables:
                self.assertIn(tbl, tables, f"Expected table {tbl} not found in database")

            # Check vector_chunks columns
            vc_cols = {col["name"] for col in inspector.get_columns("vector_chunks")}
            self.assertIn("document_version_id", vc_cols)
            self.assertIn("logical_document_id", vc_cols)
            self.assertIn("chunk_id", vc_cols)
            self.assertIn("status", vc_cols)

            # Verification Gate: Model/Schema Parity Check
            # Compare SQLModel metadata with the migrated PostgreSQL schema
            versioning_models = [
                "logical_documents",
                "ingestion_runs",
                "document_versions",
                "current_document_pointers",
                "legacy_document_version_mappings",
                "version_indexing_operations",
                "document_changes",
                "migration_unmapped_records",
            ]
            for tbl_name in versioning_models:
                self.assertIn(tbl_name, SQLModel.metadata.tables, f"Model {tbl_name} missing from SQLModel metadata")
                model_cols = set(SQLModel.metadata.tables[tbl_name].columns.keys())
                db_cols = {c["name"] for c in inspector.get_columns(tbl_name)}
                diff = model_cols - db_cols
                self.assertEqual(len(diff), 0, f"Columns in model but missing from DB for {tbl_name}: {diff}")

            # Check synthetic origin source
            synth_src = conn.execute(text(
                "SELECT url, source_type, authority_tier FROM sources WHERE url = 'system://legacy-unmapped-import'"
            )).mappings().first()
            self.assertIsNotNone(synth_src)
            self.assertEqual(synth_src["source_type"], "system_archive")
            self.assertEqual(synth_src["authority_tier"], 4)

    def test_02_composite_foreign_key_cross_document_rejection(self):
        """
        Issue 4 Acceptance Criteria:
        Verify composite foreign key (logical_document_id, current_version_id) strictly prevents
        cross-document pointer mismatch at the database level.
        """
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)
        command.upgrade(cfg, "head")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            # 1. Insert two logical documents
            src_id = conn.execute(text("SELECT id FROM sources LIMIT 1")).scalar()
            doc_a_id = conn.execute(text("""
                INSERT INTO logical_documents (source_id, document_key, primary_url, title, status)
                VALUES (:sid, 'key_doc_a', 'https://example.com/doc_a', 'Doc A', 'active')
                RETURNING id
            """), {"sid": src_id}).scalar()

            doc_b_id = conn.execute(text("""
                INSERT INTO logical_documents (source_id, document_key, primary_url, title, status)
                VALUES (:sid, 'key_doc_b', 'https://example.com/doc_b', 'Doc B', 'active')
                RETURNING id
            """), {"sid": src_id}).scalar()

            # 2. Insert version for Doc A and version for Doc B
            ver_a1_id = conn.execute(text("""
                INSERT INTO document_versions (logical_document_id, version_number, lifecycle_state, requested_url, final_url, legacy_scraper_hash, raw_byte_count, normalized_char_count, extracted_text)
                VALUES (:lid, 1, 'ready', 'https://example.com/doc_a', 'https://example.com/doc_a', 'hash_a1', 100, 50, 'Text for Doc A')
                RETURNING id
            """), {"lid": doc_a_id}).scalar()

            ver_b1_id = conn.execute(text("""
                INSERT INTO document_versions (logical_document_id, version_number, lifecycle_state, requested_url, final_url, legacy_scraper_hash, raw_byte_count, normalized_char_count, extracted_text)
                VALUES (:lid, 1, 'ready', 'https://example.com/doc_b', 'https://example.com/doc_b', 'hash_b1', 100, 50, 'Text for Doc B')
                RETURNING id
            """), {"lid": doc_b_id}).scalar()
            conn.commit()

            # 3. Attempt cross-document pointer insertion: Doc A pointing to Version B1
            with self.assertRaises(IntegrityError) as ctx:
                conn.execute(text("""
                    INSERT INTO current_document_pointers (logical_document_id, current_version_id, promoted_by)
                    VALUES (:lid, :vid, 'test')
                """), {"lid": doc_a_id, "vid": ver_b1_id})
                conn.commit()
            self.assertIn("fk_pointer_matching_doc_version", str(ctx.exception))
            conn.rollback()

            # 4. Valid pointer insertion: Doc A pointing to Version A1
            conn.execute(text("""
                INSERT INTO current_document_pointers (logical_document_id, current_version_id, promoted_by)
                VALUES (:lid, :vid, 'test')
            """), {"lid": doc_a_id, "vid": ver_a1_id})
            conn.commit()
            ptr = conn.execute(text("SELECT current_version_id FROM current_document_pointers WHERE logical_document_id = :lid"), {"lid": doc_a_id}).scalar()
            self.assertEqual(ptr, ver_a1_id)

            # 5. Verify cross-document rejection on vector_chunks composite foreign key
            legacy_doc_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text)
                VALUES (:sid, 'hash_legacy', '<html></html>', 'Text')
                RETURNING id
            """), {"sid": src_id}).scalar()

            with self.assertRaises(IntegrityError) as ctx_vc:
                conn.execute(text("""
                    INSERT INTO vector_chunks (
                        document_id, logical_document_id, document_version_id, chunk_id, status,
                        chunk_index, text, vector_id, authority_tier, chunk_metadata
                    ) VALUES (
                        :did, :lid, :vid, 'chunk_cross_test', 'active',
                        0, 'Chunk text', 'vec_cross_1', 1, '{}'
                    )
                """), {"did": legacy_doc_id, "lid": doc_a_id, "vid": ver_b1_id})
                conn.commit()
            self.assertIn("fk_vector_chunks_composite_doc_ver", str(ctx_vc.exception))
            conn.rollback()

    def test_03_vector_chunk_paired_nullability_and_status_constraints(self):
        """
        Issue 5 Acceptance Criteria:
        Verify paired nullability and status constraints on vector_chunks.
        """
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)
        command.upgrade(cfg, "head")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            src_id = conn.execute(text("SELECT id FROM sources LIMIT 1")).scalar()
            doc_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text)
                VALUES (:sid, 'hash_1', '<html></html>', 'Text')
                RETURNING id
            """), {"sid": src_id}).scalar()

            log_doc_id = conn.execute(text("""
                INSERT INTO logical_documents (source_id, document_key, primary_url, title, status)
                VALUES (:sid, 'key_chk_test', 'https://example.com/test_doc', 'Test Doc', 'active')
                RETURNING id
            """), {"sid": src_id}).scalar()

            ver_id = conn.execute(text("""
                INSERT INTO document_versions (logical_document_id, version_number, lifecycle_state, requested_url, final_url, legacy_scraper_hash, raw_byte_count, normalized_char_count, extracted_text)
                VALUES (:lid, 1, 'ready', 'https://example.com/test_doc', 'https://example.com/test_doc', 'hash_1', 100, 50, 'Text')
                RETURNING id
            """), {"lid": log_doc_id}).scalar()
            conn.commit()

            # A. Invalid: document_version_id present, logical_document_id NULL
            with self.assertRaises(IntegrityError) as ctx1:
                conn.execute(text("""
                    INSERT INTO vector_chunks (document_id, logical_document_id, document_version_id, chunk_id, status, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                    VALUES (:did, NULL, :vid, 'c_err1', 'active', 0, 'text', 'vec_err1', 1, '{}')
                """), {"did": doc_id, "vid": ver_id})
                conn.commit()
            self.assertIn("chk_vector_chunks_paired_doc_ver", str(ctx1.exception))
            conn.rollback()

            # B. Invalid: logical_document_id present, document_version_id NULL
            with self.assertRaises(IntegrityError) as ctx2:
                conn.execute(text("""
                    INSERT INTO vector_chunks (document_id, logical_document_id, document_version_id, chunk_id, status, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                    VALUES (:did, :lid, NULL, 'c_err2', 'active', 0, 'text', 'vec_err2', 1, '{}')
                """), {"did": doc_id, "lid": log_doc_id})
                conn.commit()
            self.assertIn("chk_vector_chunks_paired_doc_ver", str(ctx2.exception))
            conn.rollback()

            # C. Invalid status
            with self.assertRaises(IntegrityError) as ctx3:
                conn.execute(text("""
                    INSERT INTO vector_chunks (document_id, logical_document_id, document_version_id, chunk_id, status, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                    VALUES (:did, :lid, :vid, 'c_err3', 'unsupported_status', 0, 'text', 'vec_err3', 1, '{}')
                """), {"did": doc_id, "lid": log_doc_id, "vid": ver_id})
                conn.commit()
            self.assertIn("chk_vector_chunk_status", str(ctx3.exception))
            conn.rollback()

            # D. Valid: Both NULL (legacy unmapped row)
            conn.execute(text("""
                INSERT INTO vector_chunks (document_id, logical_document_id, document_version_id, chunk_id, status, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, NULL, NULL, 'c_valid_null', 'active', 0, 'text', 'vec_valid_null', 1, '{}')
            """), {"did": doc_id})
            conn.commit()

            # E. Valid: Both set with matching composite key
            conn.execute(text("""
                INSERT INTO vector_chunks (document_id, logical_document_id, document_version_id, chunk_id, status, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, :lid, :vid, 'c_valid_both', 'staging', 1, 'text', 'vec_valid_both', 1, '{}')
            """), {"did": doc_id, "lid": log_doc_id, "vid": ver_id})
            conn.commit()

    def test_04_deterministic_backfill_and_set_chunk_reconciliation(self):
        """
        Issues 1 & 2 Acceptance Criteria:
        Verify deterministic batch-safe backfill and set-based exhaustive chunk reconciliation.
        """
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)

        # 1. Migrate up to 009 (pre-versioning schema)
        command.upgrade(cfg, "009")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            # Seed legacy source
            conn.execute(text("""
                INSERT INTO sources (url, name, source_type, priority, authority_tier, scrape_frequency, is_active, created_at)
                VALUES ('https://www.canada.ca/en/immigration-refugees-citizenship.html', 'IRCC Official', 'government', 1, 1, 24, true, now())
            """))
            src_id = conn.execute(text("SELECT id FROM sources WHERE url = 'https://www.canada.ca/en/immigration-refugees-citizenship.html'")).scalar()

            # Target URL 1: 3 legacy documents (Doc 1 v1, Doc 2 v2, Doc 3 duplicate of Doc 2)
            url_study = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"
            d1_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'hash_v1', '<html>v1</html>', 'This is the initial comprehensive study permit requirements in Canada.', '2024-01-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('job_1', :u, :did)"), {"u": url_study, "did": d1_id})

            d2_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'hash_v2', '<html>v2</html>', 'This is the updated comprehensive study permit requirements in Canada with PAL rules.', '2024-02-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('job_1', :u, :did)"), {"u": url_study, "did": d2_id})

            d3_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'hash_v2', '<html>v2</html>', 'This is the updated comprehensive study permit requirements in Canada with PAL rules.', '2024-03-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('job_1', :u, :did)"), {"u": url_study, "did": d3_id})

            # Target URL 2: Doc with NULL scraped_at timestamp (drop not-null to test edge case migration)
            conn.execute(text("ALTER TABLE documents ALTER COLUMN scraped_at DROP NOT NULL;"))
            url_work = "https://www.canada.ca/en/immigration-refugees-citizenship/services/work-canada.html"
            d4_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'hash_w1', '<html>w1</html>', 'Official temporary foreign worker program eligibility criteria and guidelines.', NULL)
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('job_1', :u, :did)"), {"u": url_work, "did": d4_id})

            # Target URL 3: Doc with short text (<20 chars -> empty_content)
            url_invalid = "https://www.canada.ca/en/immigration-refugees-citizenship/services/empty.html"
            d5_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'hash_short', '<html>short</html>', 'short text', '2024-04-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('job_1', :u, :did)"), {"u": url_invalid, "did": d5_id})

            # Seed vector chunks
            vc1_id = conn.execute(text("""
                INSERT INTO vector_chunks (document_id, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, 0, 'Chunk 1 for D1', 'vec_d1_0', 1, '{}')
                RETURNING id
            """), {"did": d1_id}).scalar()

            vc2_id = conn.execute(text("""
                INSERT INTO vector_chunks (document_id, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, 0, 'Chunk 1 for D2', 'vec_d2_0', 1, '{}')
                RETURNING id
            """), {"did": d2_id}).scalar()

            vc3_id = conn.execute(text("""
                INSERT INTO vector_chunks (document_id, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, 0, 'Chunk 1 for D3', 'vec_d3_0', 1, '{}')
                RETURNING id
            """), {"did": d3_id}).scalar()

            vc4_id = conn.execute(text("""
                INSERT INTO vector_chunks (document_id, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, 0, 'Chunk 1 for D4', 'vec_d4_0', 1, '{}')
                RETURNING id
            """), {"did": d4_id}).scalar()

            # Seed orphan chunk pointing to non-existent document_id
            vc_orphan_id = conn.execute(text("""
                INSERT INTO vector_chunks (document_id, chunk_index, text, vector_id, authority_tier, chunk_metadata)
                VALUES (:did, 0, 'Orphan chunk without doc', 'vec_orphan_0', 1, '{}')
                RETURNING id
            """), {"did": d1_id}).scalar()  # Temporarily valid FK in 009, will simulate orphan by updating after removing FK or using an unmapped document
            conn.commit()

            # Simulate an unreferenced document_id for orphan chunk:
            conn.execute(text("ALTER TABLE vector_chunks DROP CONSTRAINT vector_chunks_document_id_fkey;"))
            conn.execute(text("UPDATE vector_chunks SET document_id = 999999 WHERE id = :oid"), {"oid": vc_orphan_id})
            conn.commit()

        # 2. Run migration 010 (applies backfill)
        command.upgrade(cfg, "010")

        # 3. Verify Backfill Invariants & Set-Based Accounting
        with engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            self.assertEqual(rev, "010")

            # Check logical documents
            log_docs = conn.execute(text("SELECT id, primary_url, status FROM logical_documents ORDER BY id")).mappings().all()
            self.assertEqual(len(log_docs), 3)

            # Study URL should have 2 versions (v1 for D1, v2 for D2/D3 deduplicated)
            study_doc = [d for d in log_docs if "study-canada" in d["primary_url"]][0]
            study_versions = conn.execute(text(
                "SELECT id, version_number, lifecycle_state, legacy_scraper_hash FROM document_versions WHERE logical_document_id = :lid ORDER BY version_number"
            ), {"lid": study_doc["id"]}).mappings().all()
            self.assertEqual(len(study_versions), 2)
            self.assertEqual(study_versions[0]["version_number"], 1)
            self.assertEqual(study_versions[1]["version_number"], 2)
            self.assertEqual(study_versions[1]["lifecycle_state"], "ready")

            # Pointer for Study URL must point to Version 2
            study_ptr = conn.execute(text(
                "SELECT current_version_id FROM current_document_pointers WHERE logical_document_id = :lid"
            ), {"lid": study_doc["id"]}).scalar()
            self.assertEqual(study_ptr, study_versions[1]["id"])

            # Legacy mappings for D1, D2, D3
            m_d1 = conn.execute(text("SELECT document_version_id, is_deduplicated FROM legacy_document_version_mappings WHERE legacy_document_id = :did"), {"did": d1_id}).mappings().first()
            self.assertEqual(m_d1["document_version_id"], study_versions[0]["id"])
            self.assertFalse(m_d1["is_deduplicated"])

            m_d2 = conn.execute(text("SELECT document_version_id, is_deduplicated FROM legacy_document_version_mappings WHERE legacy_document_id = :did"), {"did": d2_id}).mappings().first()
            self.assertEqual(m_d2["document_version_id"], study_versions[1]["id"])
            self.assertFalse(m_d2["is_deduplicated"])

            m_d3 = conn.execute(text("SELECT document_version_id, is_deduplicated FROM legacy_document_version_mappings WHERE legacy_document_id = :did"), {"did": d3_id}).mappings().first()
            self.assertEqual(m_d3["document_version_id"], study_versions[1]["id"])
            self.assertTrue(m_d3["is_deduplicated"])

            # Work URL (NULL scraped_at) should have version 1 and current pointer
            work_doc = [d for d in log_docs if "work-canada" in d["primary_url"]][0]
            work_ptr = conn.execute(text(
                "SELECT current_version_id FROM current_document_pointers WHERE logical_document_id = :lid"
            ), {"lid": work_doc["id"]}).scalar()
            self.assertIsNotNone(work_ptr)

            # Invalid page D5 should be in migration_unmapped_records with empty_content
            unmapped_doc = conn.execute(text(
                "SELECT issue_category FROM migration_unmapped_records WHERE legacy_table = 'documents' AND legacy_record_id = :did"
            ), {"did": d5_id}).scalar()
            self.assertEqual(unmapped_doc, "empty_content")

            # Vector chunks mapping and statuses
            vc1_row = conn.execute(text("SELECT status, document_version_id FROM vector_chunks WHERE id = :id"), {"id": vc1_id}).mappings().first()
            self.assertEqual(vc1_row["status"], "superseded")
            self.assertEqual(vc1_row["document_version_id"], study_versions[0]["id"])

            vc2_row = conn.execute(text("SELECT status, document_version_id FROM vector_chunks WHERE id = :id"), {"id": vc2_id}).mappings().first()
            self.assertEqual(vc2_row["status"], "active")
            self.assertEqual(vc2_row["document_version_id"], study_versions[1]["id"])

            vc3_row = conn.execute(text("SELECT status, document_version_id FROM vector_chunks WHERE id = :id"), {"id": vc3_id}).mappings().first()
            self.assertEqual(vc3_row["status"], "active")
            self.assertEqual(vc3_row["document_version_id"], study_versions[1]["id"])

            vc4_row = conn.execute(text("SELECT status, document_version_id FROM vector_chunks WHERE id = :id"), {"id": vc4_id}).mappings().first()
            self.assertEqual(vc4_row["status"], "active")
            self.assertEqual(vc4_row["document_version_id"], work_ptr)

            # Orphan chunk must be recorded in migration_unmapped_records
            orphan_record = conn.execute(text(
                "SELECT issue_category FROM migration_unmapped_records WHERE legacy_table = 'vector_chunks' AND legacy_record_id = :id"
            ), {"id": vc_orphan_id}).scalar()
            self.assertEqual(orphan_record, "orphaned_chunk")

            # Set-based Reconciliation Invariant Checks:
            # 1. Disjoint: mapped chunks INTERSECT quarantined chunks is EMPTY
            disjoint_check = conn.execute(text("""
                SELECT id FROM vector_chunks WHERE document_version_id IS NOT NULL
                INTERSECT
                SELECT legacy_record_id FROM migration_unmapped_records WHERE legacy_table = 'vector_chunks'
            """)).fetchall()
            self.assertEqual(len(disjoint_check), 0, "Disjoint violation: chunks found in both mapped and quarantined sets")

            # 2. Exhaustive: all chunks EXCEPT (mapped UNION ALL quarantined) is EMPTY
            exhaustive_check = conn.execute(text("""
                SELECT id FROM vector_chunks
                EXCEPT
                (
                    SELECT id FROM vector_chunks WHERE document_version_id IS NOT NULL
                    UNION ALL
                    SELECT legacy_record_id FROM migration_unmapped_records WHERE legacy_table = 'vector_chunks'
                )
            """)).fetchall()
            self.assertEqual(len(exhaustive_check), 0, "Exhaustive accounting violation: unaccounted chunks exist")

    def test_05_downgrade_safety_guards_and_clean_reversion(self):
        """
        Issue 3 Acceptance Criteria:
        Verify fail-closed downgrade protection against data loss, rejection on non-allowlisted DBs,
        and clean downgrade/re-upgrade lifecycle when ALEMBIC_FORCE_DATA_LOSS=true.
        """
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)
        command.upgrade(cfg, "head")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            # Populate some records into logical_documents and document_versions
            src_id = conn.execute(text("SELECT id FROM sources LIMIT 1")).scalar()
            log_id = conn.execute(text("""
                INSERT INTO logical_documents (source_id, document_key, primary_url, title, status)
                VALUES (:sid, 'k_guard', 'https://example.com/guard', 'Guard Doc', 'active')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("""
                INSERT INTO document_versions (logical_document_id, version_number, lifecycle_state, requested_url, final_url, legacy_scraper_hash, raw_byte_count, normalized_char_count, extracted_text)
                VALUES (:lid, 1, 'ready', 'https://example.com/guard', 'https://example.com/guard', 'h_guard', 100, 50, 'Text')
            """), {"lid": log_id})
            conn.commit()

        # A. Downgrade on populated DB without ALEMBIC_FORCE_DATA_LOSS must fail closed
        if "ALEMBIC_FORCE_DATA_LOSS" in os.environ:
            del os.environ["ALEMBIC_FORCE_DATA_LOSS"]

        with self.assertRaises(Exception) as ctx1:
            command.downgrade(cfg, "009")
        self.assertIn("REFUSING DESTRUCTIVE DOWNGRADE", str(ctx1.exception))

        # Check revision did not change and all rows are strictly preserved
        with engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            self.assertEqual(rev, "010")

            # Verification Gate: Confirm rollback aborted safely and preserved all tables and rows
            log_row = conn.execute(text("SELECT document_key FROM logical_documents WHERE id = :lid"), {"lid": log_id}).scalar()
            self.assertEqual(log_row, "k_guard", "Expected row in logical_documents to be preserved upon refused downgrade")
            ver_cnt = conn.execute(text("SELECT COUNT(*) FROM document_versions WHERE logical_document_id = :lid"), {"lid": log_id}).scalar()
            self.assertEqual(ver_cnt, 1, "Expected row in document_versions to be preserved upon refused downgrade")

        # B. Non-allowlisted database guard rejection test
        # We test this by checking the DISPOSABLE_DATABASE_ALLOWLIST in migration 010
        # The migration has DISPOSABLE_DATABASE_ALLOWLIST = {"visa_chatbot_test", "visa_chatbot_ci_test", "visa_chatbot_migration_test", "visa_chatbot_disposable_migration_test"}
        # If dbname is "visa_chatbot", it MUST raise RuntimeError.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "m010",
            os.path.join(backend_dir, "alembic", "versions", "010_immutable_versioning_and_ingestion_runs.py")
        )
        m010 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m010)
        self.assertNotIn("visa_chatbot", m010.DISPOSABLE_DATABASE_ALLOWLIST)

        # C. Authorized downgrade with ALEMBIC_FORCE_DATA_LOSS=true
        os.environ["ALEMBIC_FORCE_DATA_LOSS"] = "true"
        try:
            command.downgrade(cfg, "008")
            with engine.connect() as conn:
                rev_008 = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
                self.assertEqual(rev_008, "008")

                # Verify versioning tables are completely gone
                inspector = inspect(engine)
                tbls = set(inspector.get_table_names())
                self.assertNotIn("logical_documents", tbls)
                self.assertNotIn("ingestion_runs", tbls)
                self.assertNotIn("document_versions", tbls)
                self.assertNotIn("current_document_pointers", tbls)
                self.assertNotIn("legacy_document_version_mappings", tbls)
                self.assertNotIn("version_indexing_operations", tbls)
                self.assertNotIn("document_changes", tbls)
                self.assertNotIn("migration_unmapped_records", tbls)

            # D. Re-upgrade cleanly from 008 back to head (010)
            command.upgrade(cfg, "head")
            with engine.connect() as conn:
                rev_head = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
                self.assertEqual(rev_head, "010")
        finally:
            if "ALEMBIC_FORCE_DATA_LOSS" in os.environ:
                del os.environ["ALEMBIC_FORCE_DATA_LOSS"]

    def test_06_backfill_interrupted_retry_safety(self):
        """
        Verification Gate: Confirm a partially completed backfill can be retried
        without duplicate versions, mappings, or quarantine records.
        """
        recreate_disposable_db()
        cfg = get_alembic_config(DISP_URL)
        command.upgrade(cfg, "009")

        engine = create_engine(DISP_URL, poolclass=pool.NullPool)
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO sources (url, name, source_type, priority, authority_tier, scrape_frequency, is_active, created_at)
                VALUES ('https://www.canada.ca/en/services.html', 'Services Official', 'government', 1, 1, 24, true, now())
            """))
            src_id = conn.execute(text("SELECT id FROM sources WHERE url = 'https://www.canada.ca/en/services.html'")).scalar()

            url_retry = "https://www.canada.ca/en/services/immigration/retry-test.html"
            d1_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'h_retry_1', '<html>1</html>', 'Content for first snapshot retry test page.', '2024-01-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('j1', :u, :did)"), {"u": url_retry, "did": d1_id})

            d2_id = conn.execute(text("""
                INSERT INTO documents (source_id, content_hash, raw_html, extracted_text, scraped_at)
                VALUES (:sid, 'h_retry_2', '<html>2</html>', 'Updated content for second snapshot retry test page.', '2024-02-01 10:00:00+00')
                RETURNING id
            """), {"sid": src_id}).scalar()
            conn.execute(text("INSERT INTO crawled_pages (job_id, url, document_id) VALUES ('j1', :u, :did)"), {"u": url_retry, "did": d2_id})
            conn.commit()

        # Step 1: Run upgrade 010 (first backfill pass)
        command.upgrade(cfg, "010")

        # Step 2: Simulate retry of backfill execution
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location(
            "m010_retry",
            os.path.join(backend_dir, "alembic", "versions", "010_immutable_versioning_and_ingestion_runs.py")
        )
        m010 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m010)

        # Re-execute backfill function directly against the database to test idempotence/retry
        with engine.connect() as conn:
            with patch.object(m010.op, "get_bind", return_value=conn):
                m010._execute_backfill_migration()
            conn.commit()

        # Step 3: Verify Zero Duplicates across all tables
        with engine.connect() as conn:
            # Exactly 1 logical document
            log_doc_cnt = conn.execute(text("SELECT COUNT(*) FROM logical_documents WHERE primary_url = :u"), {"u": url_retry}).scalar()
            self.assertEqual(log_doc_cnt, 1, "Duplicate logical_document created during backfill retry!")

            log_doc_id = conn.execute(text("SELECT id FROM logical_documents WHERE primary_url = :u"), {"u": url_retry}).scalar()

            # Exactly 2 versions (v1 and v2)
            versions = conn.execute(text(
                "SELECT version_number FROM document_versions WHERE logical_document_id = :lid ORDER BY version_number"
            ), {"lid": log_doc_id}).scalars().all()
            self.assertEqual(versions, [1, 2], f"Expected versions [1, 2], got {versions}!")

            # Exactly 1 mapping per legacy document
            map_d1_cnt = conn.execute(text("SELECT COUNT(*) FROM legacy_document_version_mappings WHERE legacy_document_id = :did"), {"did": d1_id}).scalar()
            map_d2_cnt = conn.execute(text("SELECT COUNT(*) FROM legacy_document_version_mappings WHERE legacy_document_id = :did"), {"did": d2_id}).scalar()
            self.assertEqual(map_d1_cnt, 1)
            self.assertEqual(map_d2_cnt, 1)

            # Exactly 1 current pointer
            ptr_cnt = conn.execute(text("SELECT COUNT(*) FROM current_document_pointers WHERE logical_document_id = :lid"), {"lid": log_doc_id}).scalar()
            self.assertEqual(ptr_cnt, 1)


if __name__ == "__main__":
    unittest.main()
