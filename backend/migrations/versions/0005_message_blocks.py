"""Preserve ordered Markdown/chart snapshots without changing existing messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005_message_blocks'
down_revision = '0004_user_approval'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('messages', sa.Column('blocks', postgresql.JSONB(), nullable=False,
                                      server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column('messages', 'blocks')
