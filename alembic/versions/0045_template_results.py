"""Allow a result to belong to a template section instead of a dataset case."""

from alembic import op

revision = "0045_template_results"
down_revision = "0044_install_brief_starters"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("test_results", "test_case_id", nullable=True)


def downgrade():
    # PostgreSQL rejects this change if template results exist, preserving them.
    op.alter_column("test_results", "test_case_id", nullable=False)
