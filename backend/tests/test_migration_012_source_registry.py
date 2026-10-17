"""
Migration 012 (source registry columns, M0.10) on the disposable database.

Same safety protocol as the 010 suite: the development database is snapshotted before the suite and
must be unchanged before and after every test; only visa_chatbot_disposable_migration_test is touched.
"""

import unittest

from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

import test_migration_010_disposable as m010

REGISTRY_COLUMNS = {"registry_id", "topics", "max_age_days", "last_verified_at", "verify_status"}


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


class TestMigration012SourceRegistry(unittest.TestCase):

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

    def _source_columns(self) -> set:
        return {c["name"] for c in inspect(self.engine).get_columns("sources")}

    def test_upgrade_adds_registry_columns_with_a_unique_registry_id(self):
        command.upgrade(self.cfg, "012")
        self.assertEqual(_revision(self.engine), "012")
        self.assertTrue(REGISTRY_COLUMNS <= self._source_columns())
        indexes = {i["name"]: i for i in inspect(self.engine).get_indexes("sources")}
        self.assertTrue(indexes["ix_sources_registry_id"]["unique"])

        with self.engine.begin() as conn:
            insert = ("INSERT INTO sources (url, name, source_type, priority, scrape_frequency, is_active, "
                      "authority_tier, created_at, registry_id, topics) "
                      "VALUES (:u, 'x', 'official', 1, 168, true, 1, now(), 'pgwp-about', '[\"pgwp\"]')")
            conn.execute(text(insert), {"u": "https://www.canada.ca/a.html"})
        with self.assertRaises(Exception):  # one source per registry entry
            with self.engine.begin() as conn:
                conn.execute(text(insert), {"u": "https://www.canada.ca/b.html"})

    def test_existing_sources_keep_their_data(self):
        command.upgrade(self.cfg, "011")
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO sources (url, name, source_type, priority, scrape_frequency, is_active, "
                              "authority_tier, created_at) VALUES ('https://www.canada.ca/x.html', 'Kept', "
                              "'official', 1, 168, true, 1, now())"))
        command.upgrade(self.cfg, "012")
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT name, registry_id, topics FROM sources "
                                    "WHERE url = 'https://www.canada.ca/x.html'")).one()
        self.assertEqual(tuple(row), ("Kept", None, None))

    def test_downgrade_and_reupgrade(self):
        command.upgrade(self.cfg, "012")
        command.downgrade(self.cfg, "011")
        self.assertEqual(_revision(self.engine), "011")
        self.assertFalse(REGISTRY_COLUMNS & self._source_columns())
        command.upgrade(self.cfg, "012")
        self.assertTrue(REGISTRY_COLUMNS <= self._source_columns())


if __name__ == "__main__":
    unittest.main()
