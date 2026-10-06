"""add message_metadata column to chat_messages

Revision ID: 008
Revises: 007
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='chat_messages' AND column_name='message_metadata'"
    ))
    if not result.fetchone():
        op.add_column('chat_messages', sa.Column('message_metadata', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'message_metadata')
