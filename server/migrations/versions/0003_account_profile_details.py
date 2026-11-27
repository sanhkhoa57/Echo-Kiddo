"""Add private contact and avatar settings."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_profile_details",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("avatar_key", sa.String(32), nullable=True),
        sa.Column("avatar_image", sa.LargeBinary(), nullable=True),
        if_not_exists=True,
    )


def downgrade():
    op.drop_table("account_profile_details")
