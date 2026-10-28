"""Require administrator approval for user access; preserve chat data."""
from alembic import op
import sqlalchemy as sa

revision = "0004_user_approval"
down_revision = "0003_auth_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Existing accounts also require explicit approval. Do not carry login grants
    # across this access-policy change or revive them when an account is approved.
    op.execute("UPDATE auth_sessions SET revoked_at = now() WHERE revoked_at IS NULL")


def downgrade():
    op.drop_column("users", "blocked")
    op.drop_column("users", "is_admin")
