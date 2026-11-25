"""count how often reading a document was started, so a file that crashes the reader is given up on

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ll_document', schema=None) as batch_op:
        batch_op.add_column(sa.Column('read_attempts', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('ll_document', schema=None) as batch_op:
        batch_op.drop_column('read_attempts')
