"""Add comparable score summaries to completed Brief checks and experiments."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from ui.backend.services.brief_score_metrics import (
    factual_claim_metrics,
    saved_brief_scores,
)

revision = "0048_brief_score_summaries"
down_revision = "0047_saved_brief_quality"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    checks = (
        conn.execute(
            sa.text(
                """
        SELECT id FROM brief_citation_checks
        WHERE status = 'completed' AND check_kind = 'full'
          AND jsonb_typeof(section_results) = 'array'
    """
            )
        )
        .scalars()
        .all()
    )
    for key in checks:
        sections = (
            conn.execute(
                sa.text(
                    """
            SELECT s->>'status' AS status, s->'assertion_results' AS assertion_results
            FROM brief_citation_checks, jsonb_array_elements(section_results) s WHERE id = :id
        """
                ),
                {"id": key},
            )
            .mappings()
            .all()
        )
        conn.execute(
            sa.text(
                """
            UPDATE brief_citation_checks SET summary_stats = summary_stats || :metrics
            WHERE id = :id
        """
            ).bindparams(sa.bindparam("metrics", type_=JSONB)),
            {"id": key, "metrics": saved_brief_scores(sections)},
        )

    runs = (
        conn.execute(
            sa.text(
                """
        SELECT r.id FROM test_runs r
        JOIN test_experiments e ON e.id = r.experiment_id
        JOIN test_datasets d ON d.id = e.dataset_id
        WHERE d.capability = 'brief' AND r.status = 'completed'
    """
            )
        )
        .scalars()
        .all()
    )
    for key in runs:
        results = (
            conn.execute(
                sa.text(
                    """
            SELECT assertion_results FROM test_results WHERE run_id = :id
        """
                ),
                {"id": key},
            )
            .mappings()
            .all()
        )
        conn.execute(
            sa.text(
                """
            UPDATE test_runs SET summary_stats = summary_stats || :metrics WHERE id = :id
        """
            ).bindparams(sa.bindparam("metrics", type_=JSONB)),
            {"id": key, "metrics": factual_claim_metrics(results)},
        )
    conn.execute(
        sa.text(
            """
        UPDATE test_experiments e SET summary_stats = e.summary_stats || jsonb_build_object(
            'factual_claim_mean_score', r.summary_stats->'factual_claim_mean_score',
            'factual_claim_pass_rate', r.summary_stats->'factual_claim_pass_rate')
        FROM test_runs r WHERE r.experiment_id=e.id AND e.status='completed'
          AND r.status='completed' AND r.summary_stats ? 'factual_claim_mean_score'
          AND NOT EXISTS (SELECT 1 FROM test_runs newer WHERE newer.experiment_id=e.id
                          AND newer.run_number>r.run_number)
    """
        )
    )


def downgrade():
    """Earlier versions ignore the additional summary fields."""
