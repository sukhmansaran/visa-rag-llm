"""add crawler pipeline tables

Revision ID: 007
Revises: 006
Create Date: 2025-12-03 12:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def _table_exists(table):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name=:t"
    ), {"t": table})
    return result.fetchone() is not None


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column})
    return result.fetchone() is not None


def _index_exists(index):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname=:i"
    ), {"i": index})
    return result.fetchone() is not None


def _fk_exists(constraint):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE constraint_name=:c AND constraint_type='FOREIGN KEY'"
    ), {"c": constraint})
    return result.fetchone() is not None


def upgrade() -> None:
    # aggregator_portals — may already exist from migration 001 (simpler version)
    # Either create it fresh or add missing columns to the existing table
    if not _table_exists('aggregator_portals'):
        op.create_table(
            'aggregator_portals',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('name', sa.String(length=255), nullable=False, unique=True),
            sa.Column('tier', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('base_domains', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('category', sa.String(length=50), nullable=False, server_default='general'),
            sa.Column('throttle_rps', sa.Float(), server_default='0.5'),
            sa.Column('requires_js', sa.Boolean(), server_default='false'),
            sa.Column('extraction_config', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='true'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id')
        )
    else:
        # Table exists from 001 — add new columns that weren't in the original schema
        new_cols = [
            ('tier', sa.Integer(), '1'),
            ('base_domains', postgresql.JSON(astext_type=sa.Text()), None),
            ('category', sa.String(length=50), "'general'"),
            ('throttle_rps', sa.Float(), '0.5'),
            ('requires_js', sa.Boolean(), 'false'),
            ('extraction_config', postgresql.JSON(astext_type=sa.Text()), None),
        ]
        for col_name, col_type, default in new_cols:
            if not _column_exists('aggregator_portals', col_name):
                col = sa.Column(col_name, col_type, nullable=True)
                op.add_column('aggregator_portals', col)
                if default is not None:
                    op.execute(sa.text(
                        f"UPDATE aggregator_portals SET {col_name} = {default} WHERE {col_name} IS NULL"
                    ))
    if not _index_exists('ix_aggregator_portals_tier'):
        op.create_index('ix_aggregator_portals_tier', 'aggregator_portals', ['tier'], unique=False)

    # seed_urls
    if not _table_exists('seed_urls'):
        op.create_table(
            'seed_urls',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('portal_id', sa.Integer(), nullable=True),
            sa.Column('url', sa.String(length=2048), nullable=False, unique=True),
            sa.Column('max_depth', sa.Integer(), server_default='3'),
            sa.Column('allowed_domains', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('crawl_schedule', sa.String(length=20), server_default='weekly'),
            sa.Column('is_active', sa.Boolean(), server_default='true'),
            sa.Column('last_crawled_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['portal_id'], ['aggregator_portals.id']),
            sa.PrimaryKeyConstraint('id')
        )
    if not _index_exists('ix_seed_urls_portal_id'):
        op.create_index('ix_seed_urls_portal_id', 'seed_urls', ['portal_id'], unique=False)

    # crawl_jobs
    if not _table_exists('crawl_jobs'):
        op.create_table(
            'crawl_jobs',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('job_id', sa.String(length=64), nullable=False, unique=True),
            sa.Column('status', sa.String(length=20), server_default='pending'),
            sa.Column('seed_urls', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('config', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('pages_crawled', sa.Integer(), server_default='0'),
            sa.Column('pages_relevant', sa.Integer(), server_default='0'),
            sa.Column('pages_stored', sa.Integer(), server_default='0'),
            sa.Column('pages_failed', sa.Integer(), server_default='0'),
            sa.Column('pages_duplicate', sa.Integer(), server_default='0'),
            sa.Column('pages_robots_blocked', sa.Integer(), server_default='0'),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('paused_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id')
        )
    if not _index_exists('ix_crawl_jobs_job_id'):
        op.create_index('ix_crawl_jobs_job_id', 'crawl_jobs', ['job_id'], unique=True)

    # crawled_pages
    if not _table_exists('crawled_pages'):
        op.create_table(
            'crawled_pages',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('job_id', sa.String(length=64), nullable=True),
            sa.Column('url', sa.String(length=2048), nullable=True),
            sa.Column('parent_url', sa.String(length=2048), nullable=True),
            sa.Column('depth', sa.Integer(), server_default='0'),
            sa.Column('http_status', sa.Integer(), nullable=True),
            sa.Column('fetch_duration_ms', sa.Integer(), nullable=True),
            sa.Column('content_hash', sa.String(length=64), nullable=True),
            sa.Column('classification', sa.String(length=20), server_default='pending'),
            sa.Column('matched_keywords', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('status', sa.String(length=20), server_default='pending'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('worker_id', sa.String(length=100), nullable=True),
            sa.Column('document_id', sa.Integer(), nullable=True),
            sa.Column('fetched_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
            sa.PrimaryKeyConstraint('id')
        )
    for idx, col in [
        ('ix_crawled_pages_job_id', 'job_id'),
        ('ix_crawled_pages_url', 'url'),
        ('ix_crawled_pages_content_hash', 'content_hash'),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, 'crawled_pages', [col], unique=False)

    # program_records
    if not _table_exists('program_records'):
        op.create_table(
            'program_records',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('portal_id', sa.Integer(), nullable=True),
            sa.Column('document_id', sa.Integer(), nullable=True),
            sa.Column('source_url', sa.String(length=2048), nullable=True),
            sa.Column('program_name', sa.String(length=500), nullable=True),
            sa.Column('university_name', sa.String(length=500), nullable=True),
            sa.Column('degree_level', sa.String(length=50), nullable=True),
            sa.Column('tuition_fee', sa.Float(), nullable=True),
            sa.Column('tuition_currency', sa.String(length=3), nullable=True),
            sa.Column('duration', sa.String(length=100), nullable=True),
            sa.Column('intake_dates', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('location_city', sa.String(length=200), nullable=True),
            sa.Column('location_country', sa.String(length=100), nullable=True),
            sa.Column('entry_requirements', sa.Text(), nullable=True),
            sa.Column('language_of_instruction', sa.String(length=50), nullable=True),
            sa.Column('application_deadline', sa.String(length=100), nullable=True),
            sa.Column('scholarship_availability', sa.Boolean(), nullable=True),
            sa.Column('ucas_tariff_points', sa.Integer(), nullable=True),
            sa.Column('university_ranking', sa.Integer(), nullable=True),
            sa.Column('ranking_year', sa.Integer(), nullable=True),
            sa.Column('needs_review', sa.Boolean(), server_default='false'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['portal_id'], ['aggregator_portals.id']),
            sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
            sa.UniqueConstraint('program_name', 'university_name', name='uq_program_university'),
            sa.PrimaryKeyConstraint('id')
        )
    for idx, col in [
        ('ix_program_records_portal_id', 'portal_id'),
        ('ix_program_records_document_id', 'document_id'),
        ('ix_program_records_program_name', 'program_name'),
        ('ix_program_records_university_name', 'university_name'),
        ('ix_program_records_location_country', 'location_country'),
    ]:
        if not _index_exists(idx):
            op.create_index(idx, 'program_records', [col], unique=False)

    # portal_id column on sources — may already exist from migration 001
    if not _column_exists('sources', 'portal_id'):
        op.add_column('sources', sa.Column('portal_id', sa.Integer(), nullable=True))
    if not _fk_exists('fk_sources_portal_id'):
        op.create_foreign_key('fk_sources_portal_id', 'sources', 'aggregator_portals', ['portal_id'], ['id'])


def downgrade() -> None:
    if _fk_exists('fk_sources_portal_id'):
        op.drop_constraint('fk_sources_portal_id', 'sources', type_='foreignkey')
    if _column_exists('sources', 'portal_id'):
        op.drop_column('sources', 'portal_id')
    for t in ['program_records', 'crawled_pages', 'crawl_jobs', 'seed_urls', 'aggregator_portals']:
        if _table_exists(t):
            op.drop_table(t)
