"""multi-institution Plaid: plaid_item table, backfill, drop User.plaid_* columns

Revision ID: 035d62499d87
Revises: 33d384c0c915
Create Date: 2026-08-27

changes/008. Moves each user's single Plaid connection into a plaid_item
row (1:many), points that user's accounts at it, then drops the three
scalar plaid_* columns from user.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '035d62499d87'
down_revision = '33d384c0c915'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plaid_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plaid_item_id', sa.String(length=120), nullable=False),
        sa.Column('access_token_encrypted', sa.LargeBinary(), nullable=False),
        sa.Column('sync_cursor', sa.String(length=255), nullable=True),
        sa.Column('institution_name', sa.String(length=255), nullable=True),
        sa.Column('institution_id', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plaid_item_id'),
        sa.UniqueConstraint('user_id', 'plaid_item_id', name='uq_plaid_item_user_item'),
    )

    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plaid_item_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_account_plaid_item', 'plaid_item', ['plaid_item_id'], ['id'], ondelete='SET NULL'
        )

    # Backfill: one plaid_item per user that has a connection, then point
    # that user's accounts at it. Pre-migration is strictly one-item-per-user
    # so the account UPDATE is unambiguous; item-less users (incl. demo and
    # manual-only accounts) keep account.plaid_item_id = NULL.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO plaid_item
                (user_id, plaid_item_id, access_token_encrypted, sync_cursor,
                 institution_name, institution_id, created_at)
            SELECT id, plaid_item_id, plaid_access_token_encrypted, plaid_sync_cursor,
                   NULL, NULL, now()
            FROM "user"
            WHERE plaid_access_token_encrypted IS NOT NULL
              AND plaid_item_id IS NOT NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE account
            SET plaid_item_id = pi.id
            FROM plaid_item pi
            WHERE account.user_id = pi.user_id
            """
        )
    )

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('plaid_access_token_encrypted')
        batch_op.drop_column('plaid_item_id')
        batch_op.drop_column('plaid_sync_cursor')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plaid_access_token_encrypted', postgresql.BYTEA(), nullable=True))
        batch_op.add_column(sa.Column('plaid_item_id', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('plaid_sync_cursor', sa.String(length=255), nullable=True))

    # Lossy for users with >1 item — copy back only the earliest. Downgrade
    # is dev-only.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE "user" u
            SET plaid_access_token_encrypted = pi.access_token_encrypted,
                plaid_item_id = pi.plaid_item_id,
                plaid_sync_cursor = pi.sync_cursor
            FROM (
                SELECT DISTINCT ON (user_id) user_id, access_token_encrypted,
                       plaid_item_id, sync_cursor
                FROM plaid_item
                ORDER BY user_id, id
            ) pi
            WHERE u.id = pi.user_id
            """
        )
    )

    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_constraint('fk_account_plaid_item', type_='foreignkey')
        batch_op.drop_column('plaid_item_id')

    op.drop_table('plaid_item')
