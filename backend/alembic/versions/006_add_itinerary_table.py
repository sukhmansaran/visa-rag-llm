"""add itinerary table

Revision ID: 006
Revises: 005
Create Date: 2025-12-02 23:55:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create travel_itineraries table
    op.create_table(
        'travel_itineraries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=True),
        sa.Column('budget_tier', sa.String(length=20), nullable=True),
        sa.Column('interests', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('generated_by', sa.String(length=20), nullable=True),  # 'ai' or 'manual'
        sa.Column('itinerary_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('destinations_included', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('total_cost_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('visa_info_included', sa.Boolean(), default=False),
        sa.Column('status', sa.String(length=20), default='draft'),  # draft, confirmed, completed
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_travel_itineraries_id'), 'travel_itineraries', ['id'], unique=False)
    op.create_index(op.f('ix_travel_itineraries_user_id'), 'travel_itineraries', ['user_id'], unique=False)
    op.create_index(op.f('ix_travel_itineraries_country'), 'travel_itineraries', ['country'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_travel_itineraries_country'), table_name='travel_itineraries')
    op.drop_index(op.f('ix_travel_itineraries_user_id'), table_name='travel_itineraries')
    op.drop_index(op.f('ix_travel_itineraries_id'), table_name='travel_itineraries')
    op.drop_table('travel_itineraries')
