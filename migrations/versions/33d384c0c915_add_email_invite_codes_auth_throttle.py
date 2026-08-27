"""add User.email, invite_code, auth_throttle

Revision ID: 33d384c0c915
Revises: b2c3d4e5f6a7
Create Date: 2026-08-27

Invite-only signup (changes/007). Adds a nullable/unique email column to
user, plus the invite_code and auth_throttle tables. No data backfill —
existing users get email = NULL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '33d384c0c915'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint('uq_user_email', ['email'])

    op.create_table(
        'invite_code',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('used_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['used_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    with op.batch_alter_table('invite_code', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invite_code_code'), ['code'], unique=False)

    op.create_table(
        'auth_throttle',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('window_start', sa.DateTime(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scope', 'key', name='uq_auth_throttle_scope_key'),
    )


def downgrade():
    op.drop_table('auth_throttle')
    with op.batch_alter_table('invite_code', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invite_code_code'))
    op.drop_table('invite_code')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('uq_user_email', type_='unique')
        batch_op.drop_column('email')
