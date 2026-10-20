"""
Migration 013 (drop the unused versioning schema, M0.14b) on the disposable database.

Same safety protocol as the 010 suite: the development database is snapshotted before the suite and
must be unchanged before and after every test; only visa_chatbot_disposable_migration_test is touched.
"""

import unittest

from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

import test_migration_010_disposable as m010

DROPPED_TABLES = {
    "current_document_pointers", "legacy_document_version_mappings", "document_changes",
    "version_indexing_operations", "migration_unmapped_records", "document_versions", "ingestion_runs",
    "logical_documents",
}
DROPPED_COLUMNS = {"document_version_id", "logical_document_id", "chunk_id"}


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _schema(engine) -> dict:
    """Tables, vector_chunks columns, constraints and indexes: enough to compare two schemas."""
    insp = inspect(engine)
    return {
        "tables": set(insp.get_table_names()),
        "vector_chunks_columns": {c["name"] for c in insp.get_columns("vector_chunks")},
        "vector_chunks_checks": {c["name"] for c in insp.get_check_constraints("vector_chunks")},
        "vector_chunks_fks": {fk["name"] for fk in insp.get_foreign_keys("vector_chunks")},
        "vector_chunks_uniques": {u["name"] for u in insp.get_unique_constraints("vector_chunks")},
        "vector_chunks_indexes": {i["name"] for i in insp.get_indexes("vector_chunks")},
    }


class TestMigration013DropVersioning(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        m010._DEV_DB_BASELINE["state"] = m010.dev_db_snapshot()

    @classmethod
    def tearDownClass(cls):
        try:
            maint = create_engine(m010.MAINT_URL, isolation_level="AUTOCOMMIT")
            with maint.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {m010.DISPOSABLE_DB} WITH (FORCE);"))
        except Exception:
            pass
        m010.assert_dev_db_untouched()

    def setUp(self):
        m010.assert_dev_db_untouched()
        m010.recreate_disposable_db()
        self.cfg = m010.get_alembic_config(m010.DISP_URL)
        self.engine = create_engine(m010.DISP_URL, poolclass=pool.NullPool)

    def tearDown(self):
        self.engine.dispose()
        m010.assert_dev_db_untouched()

    def test_upgrade_drops_the_versioning_schema_and_keeps_status(self):
        command.upgrade(self.cfg, "013")
        self.assertEqual(_revision(self.engine), "013")
        schema = _schema(self.engine)
        self.assertFalse(DROPPED_TABLES & schema["tables"])
        self.assertFalse(DROPPED_COLUMNS & schema["vector_chunks_columns"])
        self.assertIn("status", schema["vector_chunks_columns"])  # used to mark superseded chunks
        self.assertIn("chk_vector_chunk_status", schema["vector_chunks_checks"])
        self.assertIn("ix_vector_chunks_status", schema["vector_chunks_indexes"])
        self.assertNotIn("fk_vector_chunks_composite_doc_ver", schema["vector_chunks_fks"])

    def test_downgrade_restores_exactly_the_012_schema(self):
        command.upgrade(self.cfg, "012")
        before = _schema(self.engine)
        command.upgrade(self.cfg, "013")
        command.downgrade(self.cfg, "012")
        self.assertEqual(_revision(self.engine), "012")
        self.assertEqual(_schema(self.engine), before)
        command.upgrade(self.cfg, "013")  # and forward again
        self.assertFalse(DROPPED_TABLES & _schema(self.engine)["tables"])

    def test_refuses_to_drop_tables_that_hold_data(self):
        command.upgrade(self.cfg, "012")
        with self.engine.begin() as conn:
            source_id = conn.execute(text("SELECT id FROM sources LIMIT 1")).scalar()
            conn.execute(text(
                "INSERT INTO logical_documents (source_id, document_key, primary_url, title, status) "
                "VALUES (:s, 'k', 'https://www.canada.ca/x.html', 'X', 'active')"), {"s": source_id})
        with self.assertRaises(RuntimeError) as err:
            command.upgrade(self.cfg, "013")
        self.assertIn("logical_documents: 1 row(s)", str(err.exception))
        self.assertEqual(_revision(self.engine), "012")
        self.assertIn("logical_documents", inspect(self.engine).get_table_names())  # nothing dropped


if __name__ == "__main__":
    unittest.main()
