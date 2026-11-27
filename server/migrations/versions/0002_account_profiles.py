"""Add editable account profiles."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("avatar_color", sa.String(12), nullable=False),
        if_not_exists=True,
    )


def downgrade():
    op.drop_table("account_profiles")
