"""add changes table

Revision ID: 003
Revises: 002
Create Date: 2025-11-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('old_hash', sa.String(length=64), nullable=False),
        sa.Column('new_hash', sa.String(length=64), nullable=False),
        sa.Column('diff_summary', sa.String(), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('notified_users', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('detected_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_changes_source_id'), 'changes', ['source_id'], unique=False)
    op.create_index(op.f('ix_changes_severity'), 'changes', ['severity'], unique=False)
    op.create_index(op.f('ix_changes_detected_at'), 'changes', ['detected_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_changes_detected_at'), table_name='changes')
    op.drop_index(op.f('ix_changes_severity'), table_name='changes')
    op.drop_index(op.f('ix_changes_source_id'), table_name='changes')
    op.drop_table('changes')
