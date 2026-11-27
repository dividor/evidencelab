"""Classify missing Brief drafts as generation errors and reconcile run counts."""

from sqlalchemy import text

from alembic import op

revision = "0046_unwritten_brief_errors"
down_revision = "0045_template_results"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Only touch rows that the old evaluator graded despite having no draft.
    runs = (
        conn.execute(
            text(
                """
        UPDATE test_results SET status = 'error', score = NULL,
            error_message = 'No Brief section was generated.',
            assertion_results = (SELECT jsonb_agg((a - 'score' - 'passed') ||
                    jsonb_build_object('not_run', true, 'message',
                        'There was no generated section to grade.') ORDER BY n)
                FROM jsonb_array_elements(CASE jsonb_typeof(assertion_results)
                    WHEN 'array' THEN assertion_results ELSE '[]'::jsonb END)
                    WITH ORDINALITY AS items(a,n))
        WHERE status IN ('fail', 'pass')
          AND actual_output->>'capability' = 'brief'
          AND (actual_output->>'written' = 'false'
               OR coalesce(actual_output->>'summary', '') !~ '[^[:space:]]')
        RETURNING run_id
    """
            )
        )
        .scalars()
        .all()
    )
    for run_id in set(runs) - {None}:
        conn.execute(
            text(
                """
            UPDATE test_runs r SET summary_stats = r.summary_stats || (
                SELECT jsonb_build_object(
                    'failed', count(*) FILTER (WHERE status = 'fail'),
                    'errored', count(*) FILTER (WHERE status = 'error'),
                    'passed', count(*) FILTER (WHERE status = 'pass'),
                    'pass_rate', round(count(*) FILTER (WHERE status = 'pass')::numeric
                        / count(*), 4),
                    'mean_score', round(avg(score)::numeric, 4))
                FROM test_results WHERE run_id = r.id)
            WHERE r.id = :run AND r.status = 'completed'
        """
            ),
            {"run": run_id},
        )
        conn.execute(
            text(
                """
            UPDATE test_experiments e SET summary_stats = r.summary_stats
            FROM test_runs r WHERE r.id = :run AND r.experiment_id = e.id
              AND r.status = 'completed' AND e.status = 'completed'
              AND NOT EXISTS (SELECT 1 FROM test_runs newer WHERE newer.experiment_id = e.id
                              AND newer.run_number > r.run_number)
        """
            ),
            {"run": run_id},
        )


def downgrade():
    """Keep corrected evaluation history."""
