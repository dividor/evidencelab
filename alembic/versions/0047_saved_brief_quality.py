"""Store section evaluations alongside versioned saved-Brief checks."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0047_saved_brief_quality"
down_revision = "0046_unwritten_brief_errors"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "brief_citation_checks",
        sa.Column(
            "check_kind", sa.String(20), nullable=False, server_default="citation"
        ),
    )
    op.add_column("brief_citation_checks", sa.Column("section_results", JSONB))


def downgrade():
    op.drop_column("brief_citation_checks", "section_results")
    op.drop_column("brief_citation_checks", "check_kind")
