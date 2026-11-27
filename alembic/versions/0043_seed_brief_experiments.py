"""Reserve the historical Brief evaluation revision."""

revision = "0043_seed_brief_experiments"
down_revision = "0042_add_activity_footprint"
branch_labels = None
depends_on = None


def upgrade():
    """Reserved revision. Users create their own experiments."""


def downgrade():
    """Keep editable experiments and their run history."""
