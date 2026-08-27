"""backfill NULL plaid_item.import_cutoff to the item's creation date

Revision ID: 8c14d99893c5
Revises: 24d3aed8ab6c
Create Date: 2026-08-27

changes/016. changes/011 left `import_cutoff` NULL for any plaid_item that
already existed, and sync treated NULL as "import everything" — so a real
connection whose item pre-dated the column pulled ~3 months of history on
its first sync. NULL now means "fall back to created_at" both at runtime
and here.
"""
from alembic import op
import sqlalchemy as sa


revision = '8c14d99893c5'
down_revision = '24d3aed8ab6c'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE plaid_item SET import_cutoff = created_at::date WHERE import_cutoff IS NULL"
        )
    )


def downgrade():
    # No-op: there's no way to know which rows were NULL before, and the
    # value is harmless if left populated.
    pass
