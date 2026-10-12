"""
Phase 1 Safety Review Regression Tests:
Database Initialization Guards and Development Database Invariant Verification.

Covers:
1. init_db() default behavior: table auto-creation disabled, verifies connectivity via SELECT 1.
2. init_db() opt-in allowed only in explicitly designated test/sandbox environments.
3. init_db() strictly rejects schema creation in production, staging, and development.
4. init_db() strictly rejects schema creation targeting protected Alembic databases (visa_chatbot).
5. assert_dev_db_untouched() fails closed on maintenance database connection failures.
6. assert_dev_db_untouched() succeeds when visa_chatbot is confirmed absent and remains absent.
7. assert_dev_db_untouched() fails if pg_database reports absent but direct probe succeeds (inconsistency).
8. dev_db_snapshot() returns (revision, tables) when visa_chatbot is present, at any revision.
9. assert_dev_db_untouched() fails if the dev DB revision or tables changed during the suite.
10. assert_dev_db_untouched() fails closed on missing alembic_version table.
11. assert_dev_db_untouched() fails closed on empty/null alembic_version metadata.
12. assert_dev_db_untouched() fails closed on unexpected connection failures to existing dev database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import init_db
from tests.test_migration_010_disposable import (
    _DEV_DB_BASELINE,
    assert_dev_db_untouched,
    dev_db_snapshot,
)


# ==============================================================================
# 1. init_db() Lifecycle & Environment Safeguard Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_init_db_default_does_not_create_tables():
    """Verify normal startup: DATABASE_AUTO_CREATE_TABLES is False, SELECT 1 ping only."""
    assert settings.DATABASE_AUTO_CREATE_TABLES is False

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with patch("app.core.database.engine", mock_engine):
        with patch("app.core.database.SQLModel.metadata.create_all") as mock_create:
            result = await init_db()

            assert result is False
            assert not mock_create.called, "create_all was called during normal startup"
            assert mock_conn.execute.called, "Connectivity check (SELECT 1) should be executed"


@pytest.mark.asyncio
async def test_init_db_opt_in_in_permitted_test_environment():
    """Verify schema creation is permitted when opted in, environment is test, and DB is disposable."""
    mock_conn = AsyncMock()
    mock_conn.run_sync = AsyncMock(side_effect=lambda fn: fn(None))

    mock_engine = MagicMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    with patch.object(settings, "DATABASE_AUTO_CREATE_TABLES", True):
        with patch.object(settings, "ENVIRONMENT", "testing"):
            with patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://postgres:1@localhost:5432/visa_chatbot_test"):
                with patch("app.core.database.engine", mock_engine):
                    with patch("app.core.database.SQLModel.metadata.create_all") as mock_create:
                        result = await init_db()

                        assert result is True
                        assert mock_create.called, "create_all should be called in permitted test environment"


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_env", ["production", "staging", "development", "prod"])
async def test_init_db_rejects_auto_create_in_forbidden_environments(forbidden_env):
    """Verify attempts to enable schema creation in non-test environments fail closed."""
    with patch.object(settings, "DATABASE_AUTO_CREATE_TABLES", True):
        with patch.object(settings, "ENVIRONMENT", forbidden_env):
            with pytest.raises(RuntimeError) as exc_info:
                await init_db()

            assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
            assert f"forbidden in '{forbidden_env}'" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("unapproved_db", ["visa_chatbot", "visa_chatbot_dev", "unknown_db", "prod_database", "test_db_unlisted"])
async def test_init_db_rejects_auto_create_targeting_unapproved_databases(unapproved_db):
    """Verify attempts to enable schema creation targeting unapproved databases fail closed."""
    with patch.object(settings, "DATABASE_AUTO_CREATE_TABLES", True):
        with patch.object(settings, "ENVIRONMENT", "testing"):
            with patch.object(settings, "DATABASE_URL", f"postgresql+asyncpg://postgres:1@localhost:5432/{unapproved_db}"):
                with pytest.raises(RuntimeError) as exc_info:
                    await init_db()

                assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
                assert f"Refusing schema auto-creation on database '{unapproved_db}'" in str(exc_info.value)
                assert "Auto-creation is exclusively permitted on designated disposable databases" in str(exc_info.value)


@pytest.mark.asyncio
async def test_init_db_rejects_auto_create_with_empty_database_name():
    """Verify attempts to enable schema creation with an empty database name fail closed."""
    with patch.object(settings, "DATABASE_AUTO_CREATE_TABLES", True):
        with patch.object(settings, "ENVIRONMENT", "testing"):
            with patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://postgres:1@localhost:5432/"):
                with pytest.raises(RuntimeError) as exc_info:
                    await init_db()

                assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
                assert "database name is empty" in str(exc_info.value)


# ==============================================================================
# 2. dev DB snapshot & untouched-guard Safety Tests
# ==============================================================================

def test_dev_db_snapshot_maintenance_failure_fails_closed():
    """Verify dev_db_snapshot fails closed when maintenance DB is down and direct probe fails."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_orig_err = MagicMock()
        mock_orig_err.pgcode = "08006"  # connection_failure
        conn_err = OperationalError("connection refused", None, mock_orig_err)

        # Both maintenance connection and direct connection fail
        mock_create.side_effect = [
            Exception("Maintenance database offline"),
            MagicMock(connect=MagicMock(side_effect=conn_err)),
        ]

        with pytest.raises(RuntimeError) as exc_info:
            dev_db_snapshot()

        assert "FAIL-CLOSED: Maintenance DB unavailable" in str(exc_info.value)


def test_dev_db_snapshot_maintenance_failure_falls_back_to_direct_probe():
    """Verify fallback direct probe reads the dev DB state when the maintenance DB is unavailable."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_dev_conn = MagicMock()
        # 1. table_exists -> 1
        # 2. version_num -> '008'
        mock_dev_conn.execute.return_value.scalar.side_effect = [1, "008"]

        mock_dev_engine = MagicMock()
        mock_dev_engine.connect.return_value.__enter__.return_value = mock_dev_conn

        mock_create.side_effect = [
            Exception("Maintenance DB offline"),
            mock_dev_engine,
        ]

        # Should succeed cleanly via supported fallback
        dev_db_snapshot()


def test_dev_db_snapshot_confirmed_absence_succeeds_when_absent():
    """Verify dev_db_snapshot succeeds when pg_database confirms absent and direct probe confirms absent."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        # Maintenance connection
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = None  # None = absent

        mock_maint_engine = MagicMock()
        mock_maint_engine.connect.return_value.__enter__.return_value = mock_maint_conn

        # Direct probe raises 3D000 (database does not exist)
        mock_orig_err = MagicMock()
        mock_orig_err.pgcode = "3D000"
        db_missing_err = OperationalError("FATAL: database \"visa_chatbot\" does not exist", None, mock_orig_err)

        mock_dev_engine = MagicMock()
        mock_dev_engine.connect.side_effect = db_missing_err

        mock_create.side_effect = [mock_maint_engine, mock_dev_engine]

        # Should return cleanly: confirmed absent and verified absent
        dev_db_snapshot()


def test_dev_db_snapshot_confirmed_absence_fails_if_direct_connect_succeeds():
    """Verify dev_db_snapshot fails closed if pg_database reported absent but direct connection succeeded."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        # Maintenance connection says absent
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = None

        mock_maint_engine = MagicMock()
        mock_maint_engine.connect.return_value.__enter__.return_value = mock_maint_conn

        # Direct connection unexpectedly connects
        mock_dev_conn = MagicMock()
        mock_dev_engine = MagicMock()
        mock_dev_engine.connect.return_value.__enter__.return_value = mock_dev_conn

        mock_create.side_effect = [mock_maint_engine, mock_dev_engine]

        with pytest.raises(RuntimeError) as exc_info:
            dev_db_snapshot()

        assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
        assert "reported absent by pg_database but direct connection succeeded" in str(exc_info.value)


def test_dev_db_snapshot_present_returns_revision_and_tables():
    """Verify dev_db_snapshot returns (revision, tables) for a present dev database, at any revision."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = 1

        mock_maint_engine = MagicMock()
        mock_maint_engine.connect.return_value.__enter__.return_value = mock_maint_conn

        mock_dev_conn = MagicMock()
        mock_dev_conn.execute.return_value.scalar.side_effect = [1, "010"]
        mock_dev_conn.execute.return_value.scalars.return_value.all.return_value = ["users", "chat_messages"]

        mock_dev_engine = MagicMock()
        mock_dev_engine.connect.return_value.__enter__.return_value = mock_dev_conn

        mock_create.side_effect = [mock_maint_engine, mock_dev_engine]

        assert dev_db_snapshot() == ("010", frozenset({"users", "chat_messages"}))


def test_assert_dev_db_untouched_passes_when_unchanged():
    baseline = ("010", frozenset({"users", "chat_messages"}))
    with patch.dict(_DEV_DB_BASELINE, {"state": baseline}),          patch("tests.test_migration_010_disposable.dev_db_snapshot", return_value=baseline):
        assert_dev_db_untouched()


def test_assert_dev_db_untouched_fails_when_revision_or_tables_change():
    """Any change to the dev DB during the migration suite is a safety violation."""
    baseline = ("010", frozenset({"users", "chat_messages"}))
    changed = ("011", frozenset({"users", "chat_messages", "new_table"}))
    with patch.dict(_DEV_DB_BASELINE, {"state": baseline}),          patch("tests.test_migration_010_disposable.dev_db_snapshot", return_value=changed):
        with pytest.raises(AssertionError) as exc_info:
            assert_dev_db_untouched()
    message = str(exc_info.value)
    assert "CRITICAL SAFETY VIOLATION" in message
    assert "revision 011" in message and "new_table" in message


def test_assert_dev_db_untouched_fails_if_dev_db_appears():
    with patch.dict(_DEV_DB_BASELINE, {"state": None}),          patch("tests.test_migration_010_disposable.dev_db_snapshot", return_value=("010", frozenset())):
        with pytest.raises(AssertionError):
            assert_dev_db_untouched()


def test_dev_db_snapshot_missing_alembic_table_fails_closed():
    """Verify dev_db_snapshot raises RuntimeError if alembic_version table is missing."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = 1

        mock_dev_conn = MagicMock()
        # Table existence query returns None (table missing)
        mock_dev_conn.execute.return_value.scalar.return_value = None

        mock_create.side_effect = [
            MagicMock(connect=MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_maint_conn)))),
            MagicMock(connect=MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_dev_conn)))),
        ]

        with pytest.raises(RuntimeError) as exc_info:
            dev_db_snapshot()

        assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
        assert "alembic_version table is missing" in str(exc_info.value)


def test_dev_db_snapshot_empty_alembic_metadata_fails_closed():
    """Verify dev_db_snapshot raises RuntimeError if alembic_version has no version_num."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = 1

        mock_dev_conn = MagicMock()
        # Table exists (1), but version_num query returns None
        mock_dev_conn.execute.return_value.scalar.side_effect = [1, None]

        mock_create.side_effect = [
            MagicMock(connect=MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_maint_conn)))),
            MagicMock(connect=MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_dev_conn)))),
        ]

        with pytest.raises(RuntimeError) as exc_info:
            dev_db_snapshot()

        assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
        assert "empty or invalid alembic_version metadata" in str(exc_info.value)


def test_dev_db_snapshot_present_connection_failure_fails_closed():
    """Verify dev_db_snapshot raises RuntimeError if visa_chatbot exists in pg_database but direct connect fails."""
    with patch("tests.test_migration_010_disposable.create_engine") as mock_create:
        mock_maint_conn = MagicMock()
        mock_maint_conn.execute.return_value.scalar.return_value = 1

        mock_orig_err = MagicMock()
        mock_orig_err.pgcode = "28P01"
        auth_err = OperationalError("password authentication failed", None, mock_orig_err)

        mock_create.side_effect = [
            MagicMock(connect=MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_maint_conn)))),
            MagicMock(connect=MagicMock(side_effect=auth_err)),
        ]

        with pytest.raises(RuntimeError) as exc_info:
            dev_db_snapshot()

        assert "FAIL-CLOSED: visa_chatbot exists in pg_database but connection failed" in str(exc_info.value)
