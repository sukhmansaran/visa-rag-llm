"""Schema integrity and missing tables: application_trackers, authority_tier, effective_date, constraints

Revision ID: 009
Revises: 008
Create Date: 2026-10-09 18:30:00

"""
from alembic import op, context
import sqlalchemy as sa


revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def _is_offline() -> bool:
    return context.is_offline_mode()


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


def _index_exists(index_name: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=:i"
    ), {"i": index_name})
    return result is not None and result.fetchone() is not None


def _constraint_exists(constraint_name: str) -> bool:
    if _is_offline():
        return False
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE table_schema='public' AND constraint_name=:c"
    ), {"c": constraint_name})
    return result is not None and result.fetchone() is not None


def _table_comment(table: str) -> str | None:
    if _is_offline():
        return None
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT obj_description((:t)::regclass, 'pg_class')"
    ), {"t": f"public.{table}"})
    if result is None:
        return None
    row = result.fetchone()
    return row[0] if row else None


def upgrade() -> None:
    # 1. Create application_trackers if not already present
    if not _table_exists('application_trackers'):
        op.create_table(
            'application_trackers',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('university_name', sa.String(length=255), nullable=False),
            sa.Column('program_name', sa.String(length=255), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='planning'),
            sa.Column('deadline', sa.DateTime(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        if not _is_offline():
            # Mark provenance so downgrade knows this table was created by Alembic 009
            op.execute("COMMENT ON TABLE application_trackers IS 'created_by_alembic_009'")

    if not _index_exists('ix_application_trackers_user_id'):
        op.create_index('ix_application_trackers_user_id', 'application_trackers', ['user_id'], unique=False)
    if not _index_exists('ix_application_trackers_university_name'):
        op.create_index('ix_application_trackers_university_name', 'application_trackers', ['university_name'], unique=False)

    # 2. Add authority_tier and effective_date to sources
    if not _column_exists('sources', 'authority_tier'):
        op.add_column('sources', sa.Column('authority_tier', sa.Integer(), nullable=False, server_default='1'))
    if not _column_exists('sources', 'effective_date'):
        op.add_column('sources', sa.Column('effective_date', sa.DateTime(), nullable=True))
    if not _index_exists('ix_sources_authority_tier'):
        op.create_index('ix_sources_authority_tier', 'sources', ['authority_tier'], unique=False)

    # 3. Add authority_tier and effective_date to vector_chunks
    if not _column_exists('vector_chunks', 'authority_tier'):
        op.add_column('vector_chunks', sa.Column('authority_tier', sa.Integer(), nullable=False, server_default='1'))
    if not _column_exists('vector_chunks', 'effective_date'):
        op.add_column('vector_chunks', sa.Column('effective_date', sa.DateTime(), nullable=True))
    if not _index_exists('ix_vector_chunks_authority_tier'):
        op.create_index('ix_vector_chunks_authority_tier', 'vector_chunks', ['authority_tier'], unique=False)

    # 4. Add composite unique constraint to watchlist (user_id, watched_type, watched_value)
    if not _constraint_exists('uq_watchlist_user_type_val'):
        if not _is_offline():
            # Safety check: ensure no duplicates exist prior to creating the unique constraint
            conn = op.get_bind()
            dup_count = conn.execute(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM watchlist 
                    GROUP BY user_id, watched_type, watched_value 
                    HAVING COUNT(*) > 1
                ) dups
            """)).scalar() or 0
            if dup_count > 0:
                raise RuntimeError(
                    f"Cannot create unique constraint 'uq_watchlist_user_type_val': "
                    f"Found {dup_count} duplicate key groups in 'watchlist'. Deduplication required."
                )
        op.create_unique_constraint(
            'uq_watchlist_user_type_val',
            'watchlist',
            ['user_id', 'watched_type', 'watched_value']
        )

    # 5. Add composite index on chat_messages (user_id, session_id)
    if not _index_exists('ix_chat_messages_user_session'):
        op.create_index(
            'ix_chat_messages_user_session',
            'chat_messages',
            ['user_id', 'session_id'],
            unique=False
        )


def downgrade() -> None:
    if _is_offline():
        op.drop_index('ix_chat_messages_user_session', table_name='chat_messages')
        op.drop_constraint('uq_watchlist_user_type_val', table_name='watchlist', type_='unique')
        op.drop_index('ix_vector_chunks_authority_tier', table_name='vector_chunks')
        op.drop_column('vector_chunks', 'effective_date')
        op.drop_column('vector_chunks', 'authority_tier')
        op.drop_index('ix_sources_authority_tier', table_name='sources')
        op.drop_column('sources', 'effective_date')
        op.drop_column('sources', 'authority_tier')
        op.drop_table('application_trackers')
        return

    # 5. Drop composite chat index
    if _index_exists('ix_chat_messages_user_session'):
        op.drop_index('ix_chat_messages_user_session', table_name='chat_messages')

    # 4. Drop watchlist composite constraint
    if _constraint_exists('uq_watchlist_user_type_val'):
        op.drop_constraint('uq_watchlist_user_type_val', table_name='watchlist', type_='unique')

    # 3. Drop vector_chunks columns & index
    if _index_exists('ix_vector_chunks_authority_tier'):
        op.drop_index('ix_vector_chunks_authority_tier', table_name='vector_chunks')
    if _column_exists('vector_chunks', 'effective_date'):
        op.drop_column('vector_chunks', 'effective_date')
    if _column_exists('vector_chunks', 'authority_tier'):
        op.drop_column('vector_chunks', 'authority_tier')

    # 2. Drop sources columns & index
    if _index_exists('ix_sources_authority_tier'):
        op.drop_index('ix_sources_authority_tier', table_name='sources')
    if _column_exists('sources', 'effective_date'):
        op.drop_column('sources', 'effective_date')
    if _column_exists('sources', 'authority_tier'):
        op.drop_column('sources', 'authority_tier')

    # 1. Drop application_trackers table safely
    if _table_exists('application_trackers'):
        comment = _table_comment('application_trackers')
        if comment == 'created_by_alembic_009':
            conn = op.get_bind()
            row_count = conn.execute(sa.text("SELECT COUNT(*) FROM application_trackers")).scalar() or 0
            if row_count > 0:
                # SAFE ROLLBACK POLICY:
                # If table contains data, do NOT drop the table to prevent accidental data destruction.
                # Remove comment marker to signify it is now an unmanaged/preserved table.
                op.execute("COMMENT ON TABLE application_trackers IS 'preserved_on_rollback_has_data'")
            else:
                # Clean fresh database downgrade: drop the table
                op.drop_table('application_trackers')
        else:
            # Table existed prior to migration 009 (e.g. created by create_all).
            # NEVER drop a pre-existing table during rollback!
            pass
