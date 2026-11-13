"""Policy watch (M7): origin and analysis on review items

origin: what fetched the page (an answer's live fetch, or the policy watch). analysis: what changed, worked out by
code, with a checked summary (app/services/policy_watch.py).

Revision ID: 015
Revises: 014
Create Date: 2026-11-13
"""
from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    if context.is_offline_mode():
        return set()
    rows = op.get_bind().execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:t"
    ), {"t": table})
    return {row[0] for row in rows}


def upgrade() -> None:
    existing = _columns('fetched_page_reviews')
    if 'origin' not in existing:
        op.add_column('fetched_page_reviews', sa.Column('origin', sa.String(length=20), nullable=False,
                                                        server_default='agent_fetch'))
    if 'analysis' not in existing:
        op.add_column('fetched_page_reviews', sa.Column('analysis', sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = _columns('fetched_page_reviews')
    if 'analysis' in existing or context.is_offline_mode():
        op.drop_column('fetched_page_reviews', 'analysis')
    if 'origin' in existing or context.is_offline_mode():
        op.drop_column('fetched_page_reviews', 'origin')
