"""Add editable Brief generation experiments for their corresponding libraries."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0043_seed_brief_experiments"
down_revision = "0042_add_activity_footprint"
branch_labels = None
depends_on = None


def _id(name):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"urn:evidencelab:brief-evals:v1:{name}")


def _table(table_name, **columns):
    return sa.table(
        table_name, *(sa.column(key, kind) for key, kind in columns.items())
    )


def _seed(source, cases):
    stamp = datetime.now(timezone.utc)
    dates = dict(
        created_at=sa.DateTime(timezone=True), updated_at=sa.DateTime(timezone=True)
    )
    ds = _table(
        "test_datasets",
        id=UUID,
        name=sa.String,
        description=sa.Text,
        capability=sa.String,
        data_source=sa.String,
        **dates,
    )
    case_table = _table(
        "test_cases",
        id=UUID,
        dataset_id=UUID,
        input=JSONB,
        notes=sa.Text,
        tags=JSONB,
        **dates,
    )
    ex = _table(
        "test_experiments",
        id=UUID,
        dataset_id=UUID,
        name=sa.String,
        status=sa.String,
        config=JSONB,
        case_expectations=JSONB,
        created_at=dates["created_at"],
    )
    name = {"uneg": "UNEG", "worldbank": "World Bank procurement"}[source]
    did = _id(source)
    op.bulk_insert(
        ds,
        [
            dict(
                id=did,
                name=f"{name} Brief sections",
                description=(
                    "Generate a section alongside an existing section and check its "
                    "evidence, writing and overlap."
                ),
                capability="brief",
                data_source=source,
                created_at=stamp,
                updated_at=stamp,
            )
        ],
    )
    columns = [
        {"type": "brief_structure"},
        {"type": "brief_length"},
        {"type": "brief_overlap"},
        {
            "type": "llm_judge",
            "threshold": 1,
            "rubric": (
                "Check factual grounding against the cited excerpts. Fail any uncited "
                "factual claim or altered population, degree of certainty, cause, "
                "figure or denominator."
            ),
        },
        {
            "type": "llm_judge",
            "threshold": 1,
            "rubric": (
                "Check coverage and section scope against the author's instructions. "
                "Allow alternative well-supported findings and clearly described "
                "limits."
            ),
        },
        {
            "type": "llm_judge",
            "threshold": 1,
            "rubric": (
                "Check the requested voice, tone, and word target. Accept a shorter "
                "answer only when the available evidence justifies the shortfall."
            ),
        },
    ]
    states = {}
    for case in cases:
        cid = _id(source + "/" + case["case"])
        payload = dict(
            query=case["topic"],
            heading=case["section"],
            target_words=case["target_words"],
            voice=case["voice"],
            guidance=case["scope_rubric"],
            siblings=[dict(title=case["sibling"], content=case["sibling_content"])],
            reference_standard={
                "source": case["source"],
                "controls": case["citation_calibration"],
            },
        )
        op.bulk_insert(
            case_table,
            [
                dict(
                    id=cid,
                    dataset_id=did,
                    input=payload,
                    tags=[case["set"]],
                    notes=case.get("expected_distinction"),
                    created_at=stamp,
                    updated_at=stamp,
                )
            ],
        )
        states[str(cid)] = {"active": True, "cols": [True] * len(columns), "ovr": []}
    op.bulk_insert(
        ex,
        [
            dict(
                id=_id(source + "/experiment"),
                dataset_id=did,
                name=f"{name} Brief quality",
                status="draft",
                config={},
                case_expectations={"columns": columns, "cases": states},
                created_at=stamp,
            )
        ],
    )


def upgrade():
    from pipeline.db.config import load_datasources_config

    configured = {
        v.get("data_subdir") or k
        for k, v in load_datasources_config()["datasources"].items()
    }
    path = Path(__file__).resolve().parents[1] / "fixtures" / "0043_brief_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    for source, label in [
        ("uneg", "development"),
        ("worldbank", "procurement_transfer"),
    ]:
        if source in configured:
            _seed(source, [case for case in cases if case["set"] == label])


def downgrade():
    table = _table("test_datasets", id=UUID)
    op.get_bind().execute(
        table.delete().where(table.c.id.in_([_id("uneg"), _id("worldbank")]))
    )
