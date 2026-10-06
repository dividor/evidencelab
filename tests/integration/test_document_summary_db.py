"""Document summaries made in the app, against the real database.

Creates a throw-away document with section-tagged chunks in the `uneg` data
source's Postgres tables, then runs the real route handlers, document payload
normalisation and pipeline summarize stage over it: sections and reading order
from the stored chunks, generating (with a stand-in model, so no LLM is
called), saving, the listing, reprocessing keeping or replacing the summary.
The document and its chunks are deleted afterwards. Audit writes are captured
rather than stored.

Requires the Docker stack (Postgres and Qdrant).
"""

import json
import sys
import uuid
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List

import pytest
from starlette.requests import Request

from pipeline.db import get_db
from pipeline.processors.summarization.summarizer import SummarizeProcessor
from pipeline.processors.summarization.summary_text import SUMMARY_USER_SET_FIELD
from ui.backend import main as main_module
from ui.backend.routes import document_summary as routes
from ui.backend.routes import documents as documents_routes
from ui.backend.services import document_summary as service
from ui.backend.utils.document_utils import normalize_document_payload

pytestmark = [pytest.mark.integration]

DATA_SOURCE = "uneg"
PIPELINE_SUMMARY = "## Summary\n\nWritten by the pipeline."
NEW_SUMMARY = "## Summary\n\nThe programme met most of its school-feeding targets."
ADMIN = SimpleNamespace(id=uuid.uuid4(), email="admin@example.org")
# (section type, text) in reading order.
SECTIONS = [
    ("executive_summary", "One: the executive summary."),
    ("findings", "Two: the first finding."),
    ("annexes", "Three: an annex table."),
    ("findings", "Four: the second finding."),
]


class StandInModel:
    """A chat model that counts its tokens and returns a fixed summary."""

    def __init__(self) -> None:
        self.prompts: List[str] = []

    def with_config(self, callbacks):
        return self

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        return SimpleNamespace(content=NEW_SUMMARY)

    def get_num_tokens(self, text: str) -> int:
        return len(text) // 4


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/document-summaries",
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.5", 1234),
            "app": main_module.app,
        }
    )


@pytest.fixture
def document():
    """A document with four stored chunks, stored out of reading order."""
    db = get_db(DATA_SOURCE)
    doc_id = str(uuid.uuid4())
    title = f"Summary integration test {doc_id[:8]}"
    db.pg.upsert_doc(
        doc_id=doc_id,
        src_doc_raw_metadata={},
        map_fields={"map_title": title},
        sys_summary=None,
        sys_fields={"sys_status": "indexed"},
    )
    db.pg.merge_doc_sys_fields(
        doc_id=doc_id,
        sys_fields={
            "sys_full_summary": PIPELINE_SUMMARY,
            "sys_summarization_method": "llm_summary",
        },
    )
    for index in (2, 0, 3, 1):
        section, text = SECTIONS[index]
        db.pg.upsert_chunk(
            chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{index}")),
            doc_id=doc_id,
            sys_text=text,
            sys_page_num=index + 1,
            sys_headings=[],
            sys_heading_path=[],
            tag_section_type=section,
            sys_fields={},
        )
    try:
        yield SimpleNamespace(id=doc_id, title=title, db=db)
    finally:
        db.pg.delete_docs_by_title(title)


@pytest.fixture
def model(monkeypatch):
    stand_in = StandInModel()
    monkeypatch.setattr(service, "get_llm", lambda **_: stand_in)
    combos = routes.get_config_model_combos(DATA_SOURCE)
    stand_in.name = next(
        c["summarization_model"]["model"]
        for c in combos.values()
        if c.get("summarization_model")
    )
    return stand_in


@pytest.fixture
def audit(monkeypatch):
    events: List[Any] = []

    async def capture(event_type, **kwargs):
        events.append((event_type, kwargs))

    monkeypatch.setattr(routes, "write_audit_event", capture)
    return events


async def _generate(document, model, **overrides: Any) -> List[Dict[str, Any]]:
    body: Dict[str, Any] = {
        "data_source": DATA_SOURCE,
        "mode": "single_prompt",
        "section_types": ["executive_summary", "findings"],
        "prompt": "Summarise in one paragraph.",
        "summary_model": {"model": model.name, "max_tokens": 1000},
    }
    body.update(overrides)
    response = await routes.generate_document_summary(
        request=_request(),
        doc_id=document.id,
        body=routes.GenerateSummaryRequest(**body),
        admin=ADMIN,
    )
    frames = []
    async for chunk in response.body_iterator:
        for part in chunk.strip().split("\n\n"):
            frames.append(json.loads(part.removeprefix("data: ")))
    return frames


async def _save(document, audit_events, method: str = "ui_single_prompt"):
    return await routes.save_document_summary(
        request=_request(),
        doc_id=document.id,
        body=routes.SaveSummaryRequest(
            data_source=DATA_SOURCE, summary=NEW_SUMMARY, method=method
        ),
        admin=ADMIN,
    )


@pytest.mark.asyncio
async def test_sections_come_from_the_stored_chunks(document, model):
    result = await routes.get_summary_sections(
        request=_request(),
        doc_id=document.id,
        data_source=DATA_SOURCE,
        model=model.name,
        max_tokens=1000,
        admin=ADMIN,
    )
    assert result["has_section_types"] is True
    assert result["sections"] == [
        {
            "section_type": "executive_summary",
            "chars": len(SECTIONS[0][1]),
            "chunks": 1,
        },
        {
            "section_type": "findings",
            "chars": len(SECTIONS[1][1]) + len(SECTIONS[3][1]),
            "chunks": 2,
        },
        {"section_type": "annexes", "chars": len(SECTIONS[2][1]), "chunks": 1},
    ]
    assert result["single_prompt"]["available"] is True


@pytest.mark.asyncio
async def test_generating_reads_the_chosen_sections_in_order_and_saves_nothing(
    document, model, audit
):
    frames = await _generate(document, model)

    assert frames[-1]["type"] == "done"
    assert frames[-1]["summary"] == NEW_SUMMARY
    (prompt,) = model.prompts
    body = prompt.split("<<<")[1].split(">>>")[0]
    assert body.index("One:") < body.index("Two:") < body.index("Four:")
    assert "Three:" not in body
    stored = document.db.pg.fetch_docs([document.id])[document.id]
    assert stored["sys_full_summary"] == PIPELINE_SUMMARY
    assert audit == []


@pytest.mark.asyncio
async def test_saving_stores_the_summary_and_the_listing_shows_who(
    document, model, audit
):
    saved = await _save(document, audit)

    stored = document.db.pg.fetch_docs([document.id])[document.id]
    assert stored["sys_full_summary"] == NEW_SUMMARY
    assert stored["sys_data"][SUMMARY_USER_SET_FIELD] is True
    assert stored["sys_data"]["sys_summarization_method"] == "ui_single_prompt"
    listed = normalize_document_payload(stored)
    assert listed["summary_user_set"] is True
    assert listed["summary_updated_by"] == ADMIN.email
    assert listed["summary_updated_at"] == saved["summary_updated_at"]
    ((event, details),) = audit
    assert event == routes.EVENT_SUMMARY_UPDATED
    assert details["details"]["previous_method"] == "llm_summary"


@pytest.mark.asyncio
async def test_reprocessing_keeps_the_summary_unless_asked_to_replace_it(
    document, model, audit, monkeypatch
):
    await _save(document, audit, method="ui_edited")
    processor = SummarizeProcessor(
        {"llm_model": {"model": "gpt-3.5-turbo"}, "context_window": 29000}
    )
    processor._initialized = True
    monkeypatch.setattr(
        processor, "_invoke_llm", lambda *a: pytest.fail("the LLM must not be called")
    )

    # The worker reads documents from Postgres (fetch_docs_by_status), sys_data included.
    stored = document.db.pg.fetch_docs([document.id])[document.id]
    kept = processor.process_document(stored)
    assert kept["success"] is True
    assert kept["updates"]["sys_full_summary"] == NEW_SUMMARY
    assert kept["updates"]["sys_summarization_method"] == "ui_edited"

    task_module = ModuleType("pipeline.utilities.tasks")
    task_module.reprocess_document = SimpleNamespace(
        delay=lambda *args: SimpleNamespace(id="task-1")
    )
    monkeypatch.setitem(sys.modules, "pipeline.utilities.tasks", task_module)
    monkeypatch.setattr(
        document.db, "get_document", lambda _id: {"id": _id, "sys_filepath": "/x.pdf"}
    )
    monkeypatch.setattr(document.db, "delete_document_chunks", lambda _id: 0)
    monkeypatch.setattr(documents_routes, "get_db_for_source", lambda _: document.db)
    await documents_routes.reprocess_document(
        document.id, data_source=DATA_SOURCE, replace_summary=True
    )

    stored = document.db.pg.fetch_docs([document.id])[document.id]
    assert stored["sys_data"][SUMMARY_USER_SET_FIELD] is False
    assert stored["sys_status"] == "queued"
