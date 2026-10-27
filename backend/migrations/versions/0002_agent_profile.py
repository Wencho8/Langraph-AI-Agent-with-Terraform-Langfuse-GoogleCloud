"""Add a minimal user profile and per-turn provider transcript/metrics."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_agent_profile"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("display_name", sa.String(120)))
    op.add_column("turns", sa.Column("agent_transcript", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("turns", sa.Column("execution_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.execute(sa.text("""
        UPDATE users SET display_name = CASE
            WHEN id = '11111111-1111-4111-8111-111111111111' THEN 'Alice'
            WHEN id = '22222222-2222-4222-8222-222222222222' THEN 'Bob'
        END
        WHERE display_name IS NULL AND id IN (
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222'
        )
    """))


def downgrade():
    op.drop_column("turns", "execution_metadata")
    op.drop_column("turns", "agent_transcript")
    op.drop_column("users", "display_name")
