"""remember that a bill ever carried a blocking finding, so editing the finding away cannot turn off the two person rule

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ll_bill', schema=None) as batch_op:
        batch_op.add_column(sa.Column('had_block', sa.Boolean(), server_default=sa.false(), nullable=False))
    # bills that still hold a blocking finding row (open or closed) already had one
    op.get_bind().execute(sa.text("UPDATE ll_bill SET had_block = :yes WHERE id IN (SELECT ref_id FROM ll_exception WHERE ref_type = 'bill' AND severity = 'block')").bindparams(yes=True))


def downgrade() -> None:
    with op.batch_alter_table('ll_bill', schema=None) as batch_op:
        batch_op.drop_column('had_block')
