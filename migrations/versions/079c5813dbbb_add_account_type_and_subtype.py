"""add account type and subtype

Revision ID: 079c5813dbbb
Revises: 8c14d99893c5
Create Date: 2026-08-27 20:47:21.099044

changes/018. Plaid's account classification (type / subtype), stored verbatim
so a credit card is no longer indistinguishable from a checking account.
Pure DDL — existing rows get NULL and are backfilled on the next sync
(_upsert_account writes both columns every time).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '079c5813dbbb'
down_revision = '8c14d99893c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('subtype', sa.String(length=40), nullable=True))


def downgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_column('subtype')
        batch_op.drop_column('type')
