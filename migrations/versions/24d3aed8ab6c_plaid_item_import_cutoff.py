"""add PlaidItem.import_cutoff

Revision ID: 24d3aed8ab6c
Revises: 035d62499d87
Create Date: 2026-08-27

changes/011. A fresh connection only imports transactions posted on/after the
connect date; existing rows get NULL (import everything, no retroactive
hiding of history that's already been categorized).
"""
from alembic import op
import sqlalchemy as sa


revision = '24d3aed8ab6c'
down_revision = '035d62499d87'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plaid_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('import_cutoff', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('plaid_item', schema=None) as batch_op:
        batch_op.drop_column('import_cutoff')
