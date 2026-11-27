"""Retain the revision for installed databases. Users create Brief evaluations."""

revision = "0044_install_brief_starters"
down_revision = "0043_seed_brief_experiments"
branch_labels = None
depends_on = None


def upgrade():
    """Install no sample datasets, cases or experiments."""


def downgrade():
    """Preserve existing experiments and run history."""
