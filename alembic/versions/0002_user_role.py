"""add user role

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("role", sa.String(), nullable=False, server_default="user"))
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_column("users", "role")