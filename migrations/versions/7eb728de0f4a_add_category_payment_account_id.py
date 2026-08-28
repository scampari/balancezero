"""add category payment_account_id

Revision ID: 7eb728de0f4a
Revises: ca283921af94
Create Date: 2026-08-27

changes/021. Binds an auto-created credit-card payment category to the card
it pays down. Pure DDL, no backfill — plaid_api._ensure_payment_category
seeds one per credit account on the next sync (_upsert_account runs for
every account every sync).
"""
from alembic import op
import sqlalchemy as sa


revision = '7eb728de0f4a'
down_revision = 'ca283921af94'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_account_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_category_payment_account', ['payment_account_id'])
        batch_op.create_foreign_key(
            'fk_category_payment_account', 'account', ['payment_account_id'], ['id'], ondelete='SET NULL'
        )


def downgrade():
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.drop_constraint('fk_category_payment_account', type_='foreignkey')
        batch_op.drop_constraint('uq_category_payment_account', type_='unique')
        batch_op.drop_column('payment_account_id')
