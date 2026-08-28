"""add transaction transfer flag

Revision ID: ca283921af94
Revises: 079c5813dbbb
Create Date: 2026-08-27

changes/019. Marks a transaction as a movement between the user's own
accounts (checking->savings, or a credit-card payment) so it can be
excluded from spending/income totals. Existing rows get false.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ca283921af94'
down_revision = '079c5813dbbb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        # server_default so the NOT NULL add succeeds against existing rows;
        # dropped immediately after — models.py's default is the source of
        # truth going forward.
        batch_op.add_column(
            sa.Column('transfer', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.alter_column('transfer', server_default=None)


def downgrade():
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_column('transfer')
