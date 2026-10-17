"""
Migration 011 (request_traces, M0.5) on the disposable database.

Same safety protocol as the 010 suite: the development database is snapshotted before the suite and
must be unchanged before and after every test; only visa_chatbot_disposable_migration_test is touched.
"""

import os
import unittest

from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

import test_migration_010_disposable as m010

TRACE_COLUMNS = {
    "id", "trace_id", "request_id", "user_id", "session_id", "endpoint", "status", "source", "latency_ms",
    "model", "model_digest", "prompt_version", "rules_version", "kb_version", "failed_over", "steps",
    "llm_calls", "query_redacted", "answer_redacted", "error", "created_at",
}


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _insert_trace(engine, trace_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO request_traces (trace_id, endpoint, status, steps, llm_calls, created_at) "
            "VALUES (:t, 'chat.answer', 'answered', '[]', '[]', now())"
        ), {"t": trace_id})


class TestMigration011RequestTraces(unittest.TestCase):

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
        os.environ.pop("ALEMBIC_FORCE_DATA_LOSS", None)

    def tearDown(self):
        os.environ.pop("ALEMBIC_FORCE_DATA_LOSS", None)
        self.engine.dispose()
        m010.assert_dev_db_untouched()

    def test_upgrade_creates_request_traces(self):
        command.upgrade(self.cfg, "011")
        self.assertEqual(_revision(self.engine), "011")

        insp = inspect(self.engine)
        self.assertIn("request_traces", insp.get_table_names())
        self.assertEqual({c["name"] for c in insp.get_columns("request_traces")}, TRACE_COLUMNS)

        indexes = {i["name"]: i for i in insp.get_indexes("request_traces")}
        for name in ("ix_request_traces_trace_id", "ix_request_traces_user_id", "ix_request_traces_session_id",
                     "ix_request_traces_status", "ix_request_traces_created_at"):
            self.assertIn(name, indexes)
        self.assertTrue(indexes["ix_request_traces_trace_id"]["unique"])

        fks = insp.get_foreign_keys("request_traces")
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0]["referred_table"], "users")
        self.assertEqual(fks[0]["options"].get("ondelete"), "CASCADE")  # account deletion removes traces (D7)

    def test_trace_id_is_unique(self):
        command.upgrade(self.cfg, "011")
        _insert_trace(self.engine, "t-1")
        with self.assertRaises(Exception):
            _insert_trace(self.engine, "t-1")

    def test_downgrade_of_empty_table_and_reupgrade(self):
        command.upgrade(self.cfg, "011")
        command.downgrade(self.cfg, "010")
        self.assertEqual(_revision(self.engine), "010")
        self.assertNotIn("request_traces", inspect(self.engine).get_table_names())

        command.upgrade(self.cfg, "011")
        self.assertEqual(_revision(self.engine), "011")
        self.assertIn("request_traces", inspect(self.engine).get_table_names())

    def test_downgrade_refuses_to_drop_traces_without_explicit_consent(self):
        command.upgrade(self.cfg, "011")
        _insert_trace(self.engine, "keep-me")

        with self.assertRaises(RuntimeError):
            command.downgrade(self.cfg, "010")
        self.assertEqual(_revision(self.engine), "011")
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM request_traces")).scalar(), 1)

        os.environ["ALEMBIC_FORCE_DATA_LOSS"] = "true"
        command.downgrade(self.cfg, "010")
        self.assertEqual(_revision(self.engine), "010")
        self.assertNotIn("request_traces", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
