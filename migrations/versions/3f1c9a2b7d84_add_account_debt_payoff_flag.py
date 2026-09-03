"""add account debt_payoff flag

Revision ID: 3f1c9a2b7d84
Revises: 7eb728de0f4a
Create Date: 2026-09-03

changes/029. Opt-in per-card flag: a `type == "credit"` account the user is
paying down gets no auto "Credit Card Payments" envelope and drops out of
the budget's credit-card fold. Existing rows get false.
"""
from alembic import op
import sqlalchemy as sa


revision = '3f1c9a2b7d84'
down_revision = '7eb728de0f4a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        # server_default so the NOT NULL add succeeds against existing rows;
        # dropped immediately after — models.py's default is the source of
        # truth going forward.
        batch_op.add_column(
            sa.Column('debt_payoff', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.alter_column('debt_payoff', server_default=None)


def downgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_column('debt_payoff')
