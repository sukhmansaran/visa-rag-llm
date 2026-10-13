"""Request traces (M0.5): one PII-redacted record per chat request

Revision ID: 011
Revises: 010
Create Date: 2026-10-14
"""
import os

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
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
    if _table_exists('request_traces'):
        return
    op.create_table(
        'request_traces',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('trace_id', sa.String(length=36), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('endpoint', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('model_digest', sa.String(length=80), nullable=True),
        sa.Column('prompt_version', sa.String(length=32), nullable=True),
        sa.Column('rules_version', sa.String(length=32), nullable=True),
        sa.Column('kb_version', sa.String(length=64), nullable=True),
        sa.Column('failed_over', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('llm_calls', sa.JSON(), nullable=False),
        sa.Column('query_redacted', sa.Text(), nullable=False, server_default=''),
        sa.Column('answer_redacted', sa.Text(), nullable=False, server_default=''),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_request_traces_trace_id', 'request_traces', ['trace_id'], unique=True)
    op.create_index('ix_request_traces_user_id', 'request_traces', ['user_id'])
    op.create_index('ix_request_traces_session_id', 'request_traces', ['session_id'])
    op.create_index('ix_request_traces_status', 'request_traces', ['status'])
    op.create_index('ix_request_traces_created_at', 'request_traces', ['created_at'])


def downgrade() -> None:
    if not context.is_offline_mode() and _table_exists('request_traces'):
        rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM request_traces")).scalar() or 0
        if rows and os.environ.get("ALEMBIC_FORCE_DATA_LOSS", "").lower() != "true":
            raise RuntimeError(
                f"Refusing to drop request_traces: it holds {rows} trace(s). "
                "Set ALEMBIC_FORCE_DATA_LOSS=true to drop them deliberately."
            )
    op.drop_table('request_traces')
