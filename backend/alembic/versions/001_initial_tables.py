"""Initial tables: users, profiles, sources, documents, vector_chunks,
user_documents, reviews, watchlist, notifications.

Revision ID: 001
Revises: 
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_is_admin', 'users', ['is_admin'])

    # --- profiles ---
    op.create_table(
        'profiles',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('education_level', sa.String(50), nullable=True),
        sa.Column('field_of_study', sa.String(200), nullable=True),
        sa.Column('gpa', sa.Float(), nullable=True),
        sa.Column('test_scores', sa.JSON(), nullable=True),
        sa.Column('work_experience', sa.Integer(), nullable=True),
        sa.Column('target_countries', sa.JSON(), nullable=True),
        sa.Column('target_universities', sa.JSON(), nullable=True),
        sa.Column('preferred_fields', sa.JSON(), nullable=True),
        sa.Column('intake_periods', sa.JSON(), nullable=True),
        sa.Column('tuition_fee_range', sa.JSON(), nullable=True),
        sa.Column('notification_preferences', sa.JSON(), nullable=True),
    )
    op.create_index('ix_profiles_user_id', 'profiles', ['user_id'])

    # --- aggregator_portals (needed by sources FK) ---
    op.create_table(
        'aggregator_portals',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('base_url', sa.String(2048), nullable=False),
        sa.Column('portal_type', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- sources ---
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('url', sa.String(2048), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('scrape_frequency', sa.Integer(), nullable=False, server_default='168'),
        sa.Column('last_scraped_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('portal_id', sa.Integer(), sa.ForeignKey('aggregator_portals.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sources_url', 'sources', ['url'])
    op.create_index('ix_sources_country', 'sources', ['country'])
    op.create_index('ix_sources_source_type', 'sources', ['source_type'])

    # --- documents ---
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('raw_html', sa.Text(), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=False),
        sa.Column('storage_url', sa.String(2048), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_documents_source_id', 'documents', ['source_id'])
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
    op.create_index('ix_documents_scraped_at', 'documents', ['scraped_at'])

    # --- vector_chunks ---
    op.create_table(
        'vector_chunks',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('vector_id', sa.String(255), nullable=False, unique=True),
        sa.Column('chunk_metadata', sa.JSON(), nullable=True),
    )
    op.create_index('ix_vector_chunks_document_id', 'vector_chunks', ['document_id'])
    op.create_index('ix_vector_chunks_vector_id', 'vector_chunks', ['vector_id'])

    # --- user_documents ---
    op.create_table(
        'user_documents',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_type', sa.String(50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_reviewed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('storage_url', sa.String(2048), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_user_documents_user_id', 'user_documents', ['user_id'])
    op.create_index('ix_user_documents_document_type', 'user_documents', ['document_type'])

    # --- reviews ---
    op.create_table(
        'reviews',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('user_documents.id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('reviewer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('comments', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_reviews_user_id', 'reviews', ['user_id'])
    op.create_index('ix_reviews_status', 'reviews', ['status'])
    op.create_index('ix_reviews_created_at', 'reviews', ['created_at'])

    # --- watchlist ---
    op.create_table(
        'watchlist',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('watched_type', sa.String(50), nullable=False),
        sa.Column('watched_value', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_watchlist_user_id', 'watchlist', ['user_id'])
    op.create_index('ix_watchlist_watched_type', 'watchlist', ['watched_type'])
    op.create_index('ix_watchlist_watched_value', 'watchlist', ['watched_value'])

    # --- notifications ---
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('related_url', sa.String(2048), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('watchlist')
    op.drop_table('reviews')
    op.drop_table('user_documents')
    op.drop_table('vector_chunks')
    op.drop_table('documents')
    op.drop_table('sources')
    op.drop_table('aggregator_portals')
    op.drop_table('profiles')
    op.drop_table('users')
