"""Campaign snapshots and persistent demo tracker."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("demo_state", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("payload", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("demo_state")
    op.drop_table("campaigns")
