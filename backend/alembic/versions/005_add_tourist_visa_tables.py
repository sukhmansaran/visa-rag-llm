"""add tourist visa tables

Revision ID: 005_tourist_visa
Revises: 004_add_payments
Create Date: 2025-12-02 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '91504d7d74ea'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tourist_destinations table
    op.create_table(
        'tourist_destinations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('rating', sa.DECIMAL(precision=2, scale=1), nullable=True),
        sa.Column('estimated_time', sa.String(length=50), nullable=True),
        sa.Column('entry_fee_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('best_time_to_visit', sa.String(length=100), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('coordinates', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tourist_destinations_id'), 'tourist_destinations', ['id'], unique=False)
    op.create_index(op.f('ix_tourist_destinations_country'), 'tourist_destinations', ['country'], unique=False)
    op.create_index(op.f('ix_tourist_destinations_city'), 'tourist_destinations', ['city'], unique=False)

    # Create tourist_visa_info table
    op.create_table(
        'tourist_visa_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('visa_required', sa.Boolean(), nullable=True),
        sa.Column('visa_types', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('processing_time', sa.String(length=100), nullable=True),
        sa.Column('validity_period', sa.String(length=100), nullable=True),
        sa.Column('visa_fee_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('requirements', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('application_process', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('interview_required', sa.Boolean(), nullable=True),
        sa.Column('online_application', sa.Boolean(), nullable=True),
        sa.Column('official_website', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('country')
    )
    op.create_index(op.f('ix_tourist_visa_info_id'), 'tourist_visa_info', ['id'], unique=False)
    op.create_index(op.f('ix_tourist_visa_info_country'), 'tourist_visa_info', ['country'], unique=True)

    # Create travel_costs table
    op.create_table(
        'travel_costs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('item_name', sa.String(length=200), nullable=True),
        sa.Column('cost_usd_min', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('cost_usd_max', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('cost_usd_avg', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('season', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_travel_costs_id'), 'travel_costs', ['id'], unique=False)
    op.create_index(op.f('ix_travel_costs_country'), 'travel_costs', ['country'], unique=False)
    op.create_index(op.f('ix_travel_costs_city'), 'travel_costs', ['city'], unique=False)
    op.create_index(op.f('ix_travel_costs_category'), 'travel_costs', ['category'], unique=False)

    # Create travel_packages table
    op.create_table(
        'travel_packages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=True),
        sa.Column('budget_tier', sa.String(length=20), nullable=True),
        sa.Column('total_cost_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('itinerary', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('included_destinations', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('cost_breakdown', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_travel_packages_id'), 'travel_packages', ['id'], unique=False)
    op.create_index(op.f('ix_travel_packages_user_id'), 'travel_packages', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_travel_packages_user_id'), table_name='travel_packages')
    op.drop_index(op.f('ix_travel_packages_id'), table_name='travel_packages')
    op.drop_table('travel_packages')
    
    op.drop_index(op.f('ix_travel_costs_category'), table_name='travel_costs')
    op.drop_index(op.f('ix_travel_costs_city'), table_name='travel_costs')
    op.drop_index(op.f('ix_travel_costs_country'), table_name='travel_costs')
    op.drop_index(op.f('ix_travel_costs_id'), table_name='travel_costs')
    op.drop_table('travel_costs')
    
    op.drop_index(op.f('ix_tourist_visa_info_country'), table_name='tourist_visa_info')
    op.drop_index(op.f('ix_tourist_visa_info_id'), table_name='tourist_visa_info')
    op.drop_table('tourist_visa_info')
    
    op.drop_index(op.f('ix_tourist_destinations_city'), table_name='tourist_destinations')
    op.drop_index(op.f('ix_tourist_destinations_country'), table_name='tourist_destinations')
    op.drop_index(op.f('ix_tourist_destinations_id'), table_name='tourist_destinations')
    op.drop_table('tourist_destinations')
