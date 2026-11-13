"""
Migration 014 (fetched_page_reviews, M5.5b) on the disposable database.

Same safety protocol as the 010 suite: the development database is snapshotted before the suite and
must be unchanged before and after every test; only visa_chatbot_disposable_migration_test is touched.
"""

import os
import unittest

from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

import test_migration_010_disposable as m010

COLUMNS = {"id", "source_id", "url", "final_url", "title", "text", "chars", "content_hash", "status", "outcome",
           "fetched_at", "reviewed_at", "reviewed_by", "created_at"}
M7_COLUMNS = {"origin", "analysis"}  # migration 015


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _insert_item(engine, content_hash: str) -> None:
    with engine.begin() as conn:
        source_id = conn.execute(text("SELECT id FROM sources WHERE url = 'https://www.canada.ca/m014.html'")).scalar()
        if source_id is None:
            source_id = conn.execute(text(
                "INSERT INTO sources (url, name, source_type, priority, authority_tier, scrape_frequency, is_active, "
                "created_at) VALUES ('https://www.canada.ca/m014.html', 'm014', 'official', 3, 1, 168, true, now()) "
                "RETURNING id")).scalar()
        conn.execute(text(
            "INSERT INTO fetched_page_reviews (source_id, url, final_url, content_hash, fetched_at, created_at) "
            "VALUES (:s, 'https://www.canada.ca/m014.html', 'https://www.canada.ca/m014.html', :h, now(), now())"
        ), {"s": source_id, "h": content_hash})


class TestMigration014ReviewQueue(unittest.TestCase):

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

    def test_upgrade_creates_the_queue_as_the_model_describes_it(self):
        command.upgrade(self.cfg, "014")
        self.assertEqual(_revision(self.engine), "014")
        insp = inspect(self.engine)
        self.assertEqual({c["name"] for c in insp.get_columns("fetched_page_reviews")}, COLUMNS)

        command.upgrade(self.cfg, "015")  # M7: origin + analysis; then the table is what the model describes
        from app.models.fetched_page import FetchedPageReview
        insp = inspect(self.engine)
        self.assertEqual({c["name"] for c in insp.get_columns("fetched_page_reviews")}, COLUMNS | M7_COLUMNS)
        self.assertEqual(set(FetchedPageReview.__table__.columns.keys()), COLUMNS | M7_COLUMNS)
        command.downgrade(self.cfg, "014")
        insp = inspect(self.engine)
        self.assertEqual({c["name"] for c in insp.get_columns("fetched_page_reviews")}, COLUMNS)

        indexes = {i["name"] for i in insp.get_indexes("fetched_page_reviews")}
        for name in ("ix_fetched_page_reviews_source_id", "ix_fetched_page_reviews_content_hash",
                     "ix_fetched_page_reviews_status", "ix_fetched_page_reviews_created_at"):
            self.assertIn(name, indexes)
        on_delete = {fk["referred_table"]: fk["options"].get("ondelete")
                     for fk in insp.get_foreign_keys("fetched_page_reviews")}
        self.assertEqual(on_delete, {"sources": "CASCADE", "users": "SET NULL"})  # deleting a reviewer keeps the item

    def test_the_same_content_of_a_page_is_queued_once(self):
        command.upgrade(self.cfg, "014")
        _insert_item(self.engine, "a" * 64)
        _insert_item(self.engine, "b" * 64)
        with self.assertRaises(Exception):
            _insert_item(self.engine, "a" * 64)

    def test_downgrade_of_empty_table_and_reupgrade(self):
        command.upgrade(self.cfg, "014")
        command.downgrade(self.cfg, "013")
        self.assertEqual(_revision(self.engine), "013")
        self.assertNotIn("fetched_page_reviews", inspect(self.engine).get_table_names())
        command.upgrade(self.cfg, "014")
        self.assertIn("fetched_page_reviews", inspect(self.engine).get_table_names())

    def test_downgrade_refuses_to_drop_review_items_without_explicit_consent(self):
        command.upgrade(self.cfg, "014")
        _insert_item(self.engine, "c" * 64)
        with self.assertRaises(RuntimeError):
            command.downgrade(self.cfg, "013")
        self.assertEqual(_revision(self.engine), "014")
        os.environ["ALEMBIC_FORCE_DATA_LOSS"] = "true"
        command.downgrade(self.cfg, "013")
        self.assertNotIn("fetched_page_reviews", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
