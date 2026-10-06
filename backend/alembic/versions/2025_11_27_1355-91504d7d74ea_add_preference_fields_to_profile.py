"""Add preference fields to profile

Revision ID: 91504d7d74ea
Revises: 004
Create Date: 2025-11-27 13:55:27.621978+00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '91504d7d74ea'
down_revision = '004'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column})
    return result.fetchone() is not None


def _table_exists(table):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name=:t"
    ), {"t": table})
    return result.fetchone() is not None


def upgrade() -> None:
    # Add preference columns to profiles if not already there (001 may have added them)
    for col_name, col_type in [
        ('preferred_fields', sa.JSON()),
        ('intake_periods', sa.JSON()),
        ('tuition_fee_range', sa.JSON()),
    ]:
        if not _column_exists('profiles', col_name):
            op.add_column('profiles', sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    for col_name in ['tuition_fee_range', 'intake_periods', 'preferred_fields']:
        if _column_exists('profiles', col_name):
            op.drop_column('profiles', col_name)
