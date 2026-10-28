"""Username credentials and revocable browser sessions; preserve existing conversations."""
from alembic import op
import sqlalchemy as sa

revision = "0003_auth_sessions"
down_revision = "0002_agent_profile"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("username", sa.String(32)))
    op.add_column("users", sa.Column("password_hash", sa.Text()))
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_check_constraint("ck_user_credentials", "users", "(username IS NULL) = (password_hash IS NULL)")
    op.create_check_constraint("ck_username_format", "users", "username IS NULL OR username ~ '^[a-z0-9_.-]{3,32}$'")
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_verifier", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(43), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade():
    op.drop_table("auth_sessions")
    op.drop_constraint("ck_username_format", "users")
    op.drop_constraint("ck_user_credentials", "users")
    op.drop_constraint("uq_users_username", "users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "username")
