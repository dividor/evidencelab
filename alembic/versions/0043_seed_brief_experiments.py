"""Add editable Brief generation experiments for their corresponding libraries."""

revision = "0043_seed_brief_experiments"
down_revision = "0042_add_activity_footprint"
branch_labels = None
depends_on = None


def upgrade():
    """The following revision installs starters after checking existing experiments."""


def downgrade():
    """Keep editable experiments and their run history."""
