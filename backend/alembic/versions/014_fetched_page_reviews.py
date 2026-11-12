"""Review queue for live-fetched pages (M5.5b, D2)

A registry page fetched live whose text differs from the stored copy waits here for an admin. Nothing in this
table is retrievable; approving ingests the reviewed text, rejecting empties it.

Revision ID: 014
Revises: 013
Create Date: 2026-11-12
"""
import os

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    if context.is_offline_mode():
        return False
    result = op.get_bind().execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"
    ), {"t": table})
    return result.fetchone() is not None


def upgrade() -> None:
    if _table_exists('fetched_page_reviews'):
        return
    op.create_table(
        'fetched_page_reviews',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('final_url', sa.String(length=2048), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('chars', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('outcome', sa.String(length=500), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_id', 'content_hash', name='uq_fetched_page_reviews_source_hash'),
    )
    op.create_index('ix_fetched_page_reviews_source_id', 'fetched_page_reviews', ['source_id'])
    op.create_index('ix_fetched_page_reviews_content_hash', 'fetched_page_reviews', ['content_hash'])
    op.create_index('ix_fetched_page_reviews_status', 'fetched_page_reviews', ['status'])
    op.create_index('ix_fetched_page_reviews_created_at', 'fetched_page_reviews', ['created_at'])


def downgrade() -> None:
    if not context.is_offline_mode():
        if not _table_exists('fetched_page_reviews'):
            return
        rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM fetched_page_reviews")).scalar() or 0
        if rows and os.environ.get("ALEMBIC_FORCE_DATA_LOSS", "").lower() != "true":
            raise RuntimeError(
                f"Refusing to drop fetched_page_reviews: it holds {rows} review item(s). "
                "Set ALEMBIC_FORCE_DATA_LOSS=true to drop them deliberately."
            )
    op.drop_table('fetched_page_reviews')
