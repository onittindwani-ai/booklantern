"""manual exchange rates

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
import sendora_core.db


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ll_fx_rate',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('rate_date', sa.Date(), nullable=False),
    sa.Column('rate', sa.String(length=24), nullable=False),
    sa.Column('note', sa.String(length=160), nullable=False),
    sa.Column('entered_by', sa.String(length=80), nullable=False),
    sa.Column('created_at', sendora_core.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('currency', 'rate_date', name='uq_ll_fx_rate_currency_date')
    )
    with op.batch_alter_table('ll_fx_rate', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ll_fx_rate_currency'), ['currency'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ll_fx_rate', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ll_fx_rate_currency'))

    op.drop_table('ll_fx_rate')
