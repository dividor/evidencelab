"""Add editable Brief generation experiments for their corresponding libraries."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert

from alembic import op

revision = "0044_install_brief_starters"
down_revision = "0043_seed_brief_experiments"
branch_labels = None
depends_on = None


def _id(name):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"urn:evidencelab:brief-evals:v1:{name}")


def _table(table_name, **columns):
    return sa.table(
        table_name, *(sa.column(key, kind) for key, kind in columns.items())
    )


def _insert(table, rows):
    op.get_bind().execute(
        insert(table).values(rows).on_conflict_do_nothing(index_elements=["id"])
    )


def _seed(source, name, cases):
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
    did = _id(source)
    _insert(
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
        {"type": "brief_intro_scope"},
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
                "State the precise question asked by the section heading and quote the words "
                "in the draft that answer it. A true finding on the broader topic or compliance "
                "with exclusions alone earns no credit. Check coverage of each requested part. "
                "Accept a clearly stated limit where evidence is unavailable."
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
        {
            "type": "llm_judge",
            "threshold": 1,
            "rubric": (
                "Does the section read as developed, connected prose? Look for an opening "
                "answer followed by evidence, explanation or qualification of the same "
                "point. Fail a succession of isolated fact summaries, even when each "
                "is cited. Accept a concise introduction or a short paragraph with a "
                "clear purpose. Judge the writing against the requested voice and length."
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
            siblings=case.get("siblings", []),
            children=case.get("children", []),
            reference_standard=(
                {
                    "source": case["source"],
                    "controls": case["citation_calibration"],
                }
                if "source" in case
                else {}
            ),
        )
        _insert(
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
        enabled = {
            "brief_intro_scope": bool(payload["children"]),
            "brief_overlap": any(
                s.get("content") for s in (*payload["children"], *payload["siblings"])
            ),
        }
        states[str(cid)] = {
            "active": True,
            "cols": [enabled.get(c["type"], True) for c in columns],
            "ovr": [],
        }
    _insert(
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

    datasets = _table("test_datasets", id=UUID, capability=sa.String)
    experiments = _table("test_experiments", dataset_id=UUID)
    existing = (
        sa.select(1)
        .select_from(
            experiments.join(datasets, datasets.c.id == experiments.c.dataset_id)
        )
        .where(datasets.c.capability == "brief")
    )
    if op.get_bind().scalar(sa.select(existing.exists())):
        return
    configured = {
        v.get("data_subdir") or k: k
        for k, v in load_datasources_config()["datasources"].items()
    }
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "0043_brief_cases.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    sources = {
        "uneg": ("UNEG", "development"),
        "worldbank": ("World Bank procurement", "procurement_transfer"),
    }
    for source in configured.keys() & sources.keys():
        name, label = sources[source]
        selected = [
            {
                **case,
                "siblings": [
                    {"title": case["sibling"], "content": case["sibling_content"]}
                ],
            }
            for case in cases
            if case["set"] == label
        ]
        case = selected[0]
        introduction = {
            **case,
            "case": "overview-with-children",
            "section": case["topic"],
            "target_words": 100,
            "scope_rubric": (
                "Introduce the shared subject. Leave the detailed findings "
                "to the two subheadings."
            ),
            "siblings": [],
            "children": [
                {"title": case["section"], "level": 2},
                {**case["siblings"][0], "level": 2},
            ],
            "expected_distinction": (
                "The overview frames both subheadings and leaves them "
                "room to answer their own questions."
            ),
        }
        _seed(source, name, [*selected, introduction])
    if not (configured.keys() & sources.keys()):
        generic = fixture.with_name("0044_generic_brief_cases.json")
        for source, name in configured.items():
            _seed(source, name, json.loads(generic.read_text(encoding="utf-8")))


def downgrade():
    """Keep editable experiments and their run history."""
