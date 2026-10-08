"""Document summaries generated, edited and saved from the Documents screen."""

import inspect
import json
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from pipeline.db import config as pipeline_config
from pipeline.processors.summarization.summary_text import (
    SUMMARY_USER_SET_FIELD,
    SummaryTooLargeError,
    TokenCountUnavailableError,
    default_summary_instructions,
)
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from ui.backend import main as main_module
from ui.backend.auth.users import current_superuser
from ui.backend.routes import document_summary as routes
from ui.backend.services import document_summary as service
from ui.backend.utils.document_utils import normalize_document_payload

pytestmark = pytest.mark.unit

DOC_ID = "doc-7"
SUMMARY = "## Summary\n\nThe programme reached most of its targets. " * 2
SUMMARIZE = {
    "llm_model": {"model": "pipeline-model"},
    "llm_workers": 1,
    "context_window": 29000,
    "mode": "map_reduce",
    "single_prompt_context_window": 100000,
}


def _chunk(index: int, section: Any, text: str) -> Dict[str, Any]:
    chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{DOC_ID}_{index}"))
    return {"id": chunk_id, "tag_section_type": section, "sys_text": text}


# Stored out of order, as Postgres returns them.
CHUNKS = [
    _chunk(2, "findings", "Third: findings."),
    _chunk(0, "executive_summary", "First: executive summary."),
    _chunk(3, "annexes", "Fourth: annex tables."),
    _chunk(1, "findings", "Second: more findings."),
]


@pytest.fixture
def summarize_config(monkeypatch):
    config = dict(SUMMARIZE)
    monkeypatch.setattr(service, "get_summarize_config", lambda _: config)
    return config


class FakeLLM:
    """Stands in for a LangChain chat model; records prompts."""

    def __init__(self, reply: str = SUMMARY) -> None:
        self.reply = reply
        self.prompts: List[str] = []
        self.callbacks: List[Any] = []

    def with_config(self, callbacks):
        self.callbacks = callbacks
        return self

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        return SimpleNamespace(content=self.reply)

    def get_num_tokens(self, text: str) -> int:
        # Its own token count: four characters a token.
        return len(text) // 4


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    calls = []

    def get_llm(**kwargs):
        calls.append(kwargs)
        return llm

    monkeypatch.setattr(service, "get_llm", get_llm)
    llm.get_llm_calls = calls
    return llm


class TestText:
    def test_reading_order_comes_from_the_chunk_ids(self):
        ordered = service.reading_order(DOC_ID, CHUNKS)
        assert [c["sys_text"].split(":")[0] for c in ordered] == [
            "First",
            "Second",
            "Third",
            "Fourth",
        ]

    def test_a_chunk_that_does_not_follow_the_numbering_is_an_error(self):
        stray = {"id": "not-a-uuid5", "tag_section_type": "findings", "sys_text": "x"}
        with pytest.raises(ValueError, match="Cannot order 1 chunk"):
            service.reading_order(DOC_ID, [*CHUNKS, stray])

    def test_select_text_keeps_the_chosen_sections_in_order(self):
        text = service.select_text(DOC_ID, CHUNKS, ["findings", "executive_summary"])
        assert text == (
            "First: executive summary.\n\nSecond: more findings.\n\nThird: findings."
        )

    def test_an_untagged_document_uses_all_its_text(self):
        untagged = [{**c, "tag_section_type": None} for c in CHUNKS]
        text = service.select_text(DOC_ID, untagged, ["findings"])
        assert text.startswith("First") and text.endswith("annex tables.")
        assert service.has_section_types(untagged) is False

    def test_sections_without_text_are_an_error_the_user_sees(self):
        with pytest.raises(service.DocumentSummaryError, match="chosen sections"):
            service.select_text(DOC_ID, CHUNKS, ["recommendations"])
        with pytest.raises(service.DocumentSummaryError, match="no stored text"):
            service.select_text(DOC_ID, [], ["findings"])

    def test_section_breakdown_follows_the_standard_order(self):
        breakdown = service.section_breakdown(
            [*CHUNKS, {"id": "x", "tag_section_type": None, "sys_text": "abc"}]
        )
        assert [b["section_type"] for b in breakdown] == [
            "executive_summary",
            "findings",
            "annexes",
            "untagged",
        ]
        findings = next(b for b in breakdown if b["section_type"] == "findings")
        assert findings == {
            "section_type": "findings",
            "chars": len("Third: findings.") + len("Second: more findings."),
            "chunks": 2,
        }


class TestDefaults:
    def test_defaults_come_from_config(self, summarize_config):
        defaults = service.summary_defaults("wfp")
        assert defaults["mode"] == "map_reduce"
        assert defaults["section_types"] == SECTION_TYPES
        assert defaults["prompt"] == default_summary_instructions()
        assert defaults["single_prompt_context_window"] == 100000

    def test_configured_section_types_are_used_and_checked(self, summarize_config):
        summarize_config["section_types"] = ["findings", "conclusions"]
        assert service.summary_defaults("wfp")["section_types"] == [
            "findings",
            "conclusions",
        ]
        summarize_config["section_types"] = ["findings", "chapter_one"]
        with pytest.raises(ValueError, match="chapter_one"):
            service.summary_defaults("wfp")

    def test_summarize_config_matches_key_or_data_subdir(self, monkeypatch):
        monkeypatch.setattr(
            pipeline_config,
            "load_datasources_config",
            lambda: {
                "datasources": {
                    "WFP Reports": {
                        "data_subdir": "wfp",
                        "pipeline": {"summarize": {"mode": "single_prompt"}},
                    }
                }
            },
        )
        assert pipeline_config.get_summarize_config("wfp")["mode"] == "single_prompt"
        assert pipeline_config.get_summarize_config("WFP Reports")["mode"] == (
            "single_prompt"
        )
        with pytest.raises(ValueError, match="other"):
            pipeline_config.get_summarize_config("other")


class TestGenerate:
    def _generate(self, **overrides: Any) -> Dict[str, Any]:
        args: Dict[str, Any] = {
            "mode": "map_reduce",
            "section_types": ["executive_summary", "findings"],
            "prompt": "Summarise the findings in two sentences.",
            "model": "gemini-2.5-flash",
            "max_tokens": 1500,
            "temperature": 0.2,
        }
        args.update(overrides)
        return service.generate_summary("wfp", DOC_ID, CHUNKS, **args)

    def test_uses_the_chosen_model_sections_and_prompt(
        self, summarize_config, fake_llm
    ):
        result = self._generate()

        assert fake_llm.get_llm_calls == [
            {"model": "gemini-2.5-flash", "temperature": 0.2, "max_tokens": 1500}
        ]
        (prompt,) = fake_llm.prompts
        assert "First: executive summary." in prompt
        assert "annex tables" not in prompt
        assert prompt.endswith("Summarise the findings in two sentences.")
        assert result["summary"] == SUMMARY.strip()
        assert (result["method"], result["calls"]) == ("ui_map_reduce", 1)
        assert fake_llm.callbacks == [result["usage"]]

    def test_single_prompt_uses_the_default_window_when_none_is_set(
        self, summarize_config, fake_llm
    ):
        del summarize_config["single_prompt_context_window"]
        result = self._generate(mode="single_prompt")
        assert (result["method"], result["calls"]) == ("ui_single_prompt", 1)
        assert service.summary_defaults("wfp")["single_prompt_context_window"] == (
            1_048_576
        )

    def test_single_prompt_too_large_is_reported_in_tokens(
        self, summarize_config, fake_llm
    ):
        summarize_config["single_prompt_context_window"] = 4000
        big = [_chunk(i, "findings", "w" * 4000) for i in range(6)]
        with pytest.raises(SummaryTooLargeError, match="tokens a single prompt"):
            service.generate_summary(
                "wfp",
                DOC_ID,
                big,
                mode="single_prompt",
                section_types=["findings"],
                prompt="Summarise.",
                model="m",
                max_tokens=500,
                temperature=None,
            )
        assert fake_llm.prompts == []

    def test_single_prompt_needs_a_model_that_counts_tokens(
        self, summarize_config, monkeypatch
    ):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        monkeypatch.setattr(
            service, "get_llm", lambda **_: FakeListChatModel(responses=[SUMMARY])
        )
        with pytest.raises(TokenCountUnavailableError):
            self._generate(mode="single_prompt")
        info = service.single_prompt_info("wfp", "m", 2000)
        assert info["available"] is False
        assert "cannot count its tokens" in info["reason"]

    def test_saved_fields_mark_the_summary_as_set_in_the_app(self):
        updates = service.summary_updates(SUMMARY, "ui_edited", "admin@example.org")
        assert updates["sys_full_summary"] == SUMMARY
        assert updates["sys_summarization_method"] == "ui_edited"
        assert updates[SUMMARY_USER_SET_FIELD] is True
        assert updates[service.UPDATED_BY_FIELD] == "admin@example.org"
        assert updates[service.UPDATED_AT_FIELD]

    def test_listing_exposes_the_summary_state(self):
        payload = normalize_document_payload(
            {
                "sys_full_summary": SUMMARY,
                "sys_data": {
                    SUMMARY_USER_SET_FIELD: True,
                    "sys_summarization_method": "ui_single_prompt",
                    "sys_summary_updated_by": "admin@example.org",
                },
            }
        )
        assert payload["summary_user_set"] is True
        assert payload["summarization_method"] == "ui_single_prompt"
        assert payload["summary_updated_by"] == "admin@example.org"


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.9", 1234),
            "app": main_module.app,
        }
    )


ADMIN = SimpleNamespace(id=uuid.uuid4(), email="admin@example.org")


class FakePg:
    def __init__(self, doc: Dict[str, Any] | None = None) -> None:
        self.doc = (
            doc
            if doc is not None
            else {
                "map_title": "Ethiopia evaluation",
                "sys_data": {"sys_summarization_method": "llm_summary"},
            }
        )

    def fetch_docs(self, ids):
        return {DOC_ID: self.doc} if self.doc else {}

    def fetch_chunks_for_doc(self, doc_id):
        return CHUNKS


@pytest.fixture
def route_env(monkeypatch, summarize_config):
    pg = FakePg()
    monkeypatch.setattr(routes, "get_pg_for_source", lambda _: pg)
    monkeypatch.setattr(
        routes,
        "get_config_model_combos",
        lambda _: {"Vertex": {"summarization_model": {"model": "gemini-2.5-flash"}}},
    )
    usage_records: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        routes,
        "schedule_llm_usage_recording",
        lambda **kw: usage_records.append(kw),
    )
    audit: List[Any] = []

    async def capture(event_type, **kwargs):
        audit.append((event_type, kwargs))

    monkeypatch.setattr(routes, "write_audit_event", capture)
    return SimpleNamespace(pg=pg, usage=usage_records, audit=audit)


async def _frames(response) -> List[Dict[str, Any]]:
    frames = []
    async for chunk in response.body_iterator:
        for line in chunk.strip().split("\n\n"):
            frames.append(json.loads(line.removeprefix("data: ")))
    return frames


def _body(**overrides: Any) -> routes.GenerateSummaryRequest:
    data: Dict[str, Any] = {
        "data_source": "wfp",
        "mode": "map_reduce",
        "section_types": ["findings"],
        "prompt": "Summarise.",
        "summary_model": {"model": "gemini-2.5-flash", "max_tokens": 1000},
    }
    data.update(overrides)
    return routes.GenerateSummaryRequest(**data)


class TestRoutes:
    @pytest.mark.parametrize(
        "handler",
        [
            routes.get_summary_settings,
            routes.get_summary_sections,
            routes.generate_document_summary,
            routes.save_document_summary,
        ],
    )
    def test_every_route_needs_a_superuser(self, handler):
        param = inspect.signature(handler).parameters["admin"]
        assert param.default.dependency is current_superuser

    def test_the_router_has_the_four_routes(self):
        # Mounted under /document-summaries with the user module (main.py);
        # tests/integration/test_document_summary_api.py checks it over HTTP.
        routes_by_path = {
            (r.path, tuple(sorted(r.methods))) for r in routes.router.routes
        }
        assert routes_by_path == {
            ("/settings", ("GET",)),
            ("/{doc_id}/sections", ("GET",)),
            ("/{doc_id}/generate", ("POST",)),
            ("/{doc_id}", ("PUT",)),
        }

    def test_unknown_section_types_are_rejected(self):
        with pytest.raises(ValueError, match="chapter_one"):
            _body(section_types=["chapter_one"])
        with pytest.raises(ValueError, match="at least one"):
            _body(section_types=[])

    @pytest.mark.asyncio
    async def test_generate_streams_progress_then_the_summary(
        self, route_env, fake_llm
    ):
        response = await routes.generate_document_summary(
            request=_request("/document-summaries/doc-7/generate"),
            doc_id=DOC_ID,
            body=_body(),
            admin=ADMIN,
        )
        frames = await _frames(response)

        assert frames[0] == {"type": "meta", "has_section_types": True}
        assert frames[1] == {"type": "progress", "stage": "single"}
        done = frames[-1]
        assert done["type"] == "done"
        assert done["summary"] == SUMMARY.strip()
        assert (done["method"], done["calls"]) == ("ui_map_reduce", 1)
        assert "usage" not in done
        (record,) = route_env.usage
        assert record["activity_type"] == "document_summary"
        assert record["user_id"] == ADMIN.id
        assert route_env.audit == []  # generating saves nothing

    @pytest.mark.asyncio
    async def test_a_problem_the_user_can_fix_is_shown(self, route_env, fake_llm):
        response = await routes.generate_document_summary(
            request=_request("/document-summaries/doc-7/generate"),
            doc_id=DOC_ID,
            body=_body(section_types=["recommendations"]),
            admin=ADMIN,
        )
        frames = await _frames(response)
        assert frames[-1] == {
            "type": "error",
            "error": "None of the chosen sections has any text in this document",
        }

    @pytest.mark.asyncio
    async def test_an_unexpected_failure_hides_its_details(
        self, route_env, monkeypatch
    ):
        def broken(**kwargs):
            raise RuntimeError("provider said: secret internal detail")

        monkeypatch.setattr(service, "get_llm", broken)
        response = await routes.generate_document_summary(
            request=_request("/document-summaries/doc-7/generate"),
            doc_id=DOC_ID,
            body=_body(),
            admin=ADMIN,
        )
        frames = await _frames(response)
        assert frames[-1] == {
            "type": "error",
            "error": "The summary could not be generated.",
        }

    @pytest.mark.asyncio
    async def test_a_model_outside_the_combos_is_refused(self, route_env):
        body = _body(summary_model={"model": "some-other-model"})
        with pytest.raises(HTTPException) as err:
            await routes.generate_document_summary(
                request=_request("/x"), doc_id=DOC_ID, body=body, admin=ADMIN
            )
        assert err.value.status_code == 400

    @pytest.mark.asyncio
    async def test_a_missing_document_is_404(self, route_env):
        route_env.pg.doc = {}
        with pytest.raises(HTTPException) as err:
            await routes.generate_document_summary(
                request=_request("/x"), doc_id=DOC_ID, body=_body(), admin=ADMIN
            )
        assert err.value.status_code == 404

    @pytest.mark.asyncio
    async def test_save_writes_the_summary_and_an_audit_event(
        self, route_env, monkeypatch
    ):
        saved: List[Any] = []
        db = SimpleNamespace(
            update_document=lambda doc_id, u: saved.append((doc_id, u))
        )
        monkeypatch.setattr(routes, "get_db_for_source", lambda _: db)
        body = routes.SaveSummaryRequest(
            data_source="wfp", summary=SUMMARY, method="ui_edited"
        )

        result = await routes.save_document_summary(
            request=_request("/document-summaries/doc-7"),
            doc_id=DOC_ID,
            body=body,
            admin=ADMIN,
        )

        ((doc_id, updates),) = saved
        assert doc_id == DOC_ID
        assert updates["sys_full_summary"] == SUMMARY
        assert updates[SUMMARY_USER_SET_FIELD] is True
        assert result["summary_user_set"] is True
        ((event, details),) = route_env.audit
        assert event == routes.EVENT_SUMMARY_UPDATED
        assert details["user_email"] == ADMIN.email
        assert details["ip_address"] == "203.0.113.9"
        assert details["details"]["method"] == "ui_edited"
        assert details["details"]["title"] == "Ethiopia evaluation"
        assert details["details"]["previous_method"] == "llm_summary"

    @pytest.mark.asyncio
    async def test_settings_without_a_data_source_give_every_sources_defaults(
        self, route_env, monkeypatch
    ):
        monkeypatch.setattr(
            service,
            "load_datasources_config",
            lambda: {
                "datasources": {
                    "WFP Reports": {
                        "data_subdir": "wfp",
                        "pipeline": {"summarize": {"mode": "single_prompt"}},
                    },
                    "World Bank": {
                        "data_subdir": "worldbank",
                        "pipeline": {
                            "summarize": {"section_types": ["findings", "conclusions"]}
                        },
                    },
                    "No summaries": {"data_subdir": "other", "pipeline": {}},
                }
            },
        )
        settings = await routes.get_summary_settings(
            request=_request("/document-summaries/settings"),
            data_source=None,
            admin=ADMIN,
        )
        assert settings == {
            "prompt": default_summary_instructions(),
            "modes": ["map_reduce", "single_prompt"],
            "all_section_types": SECTION_TYPES,
            "data_sources": [
                {
                    "key": "wfp",
                    "name": "WFP Reports",
                    "mode": "single_prompt",
                    "section_types": SECTION_TYPES,
                },
                {
                    "key": "worldbank",
                    "name": "World Bank",
                    "mode": "map_reduce",
                    "section_types": ["findings", "conclusions"],
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_settings_for_a_data_source_add_its_config(self, route_env):
        settings = await routes.get_summary_settings(
            request=_request("/document-summaries/settings"),
            data_source="wfp",
            admin=ADMIN,
        )
        assert settings["mode"] == "map_reduce"
        assert settings["section_types"] == SECTION_TYPES
        assert settings["single_prompt_context_window"] == 100000

    @pytest.mark.asyncio
    async def test_sections_report_sizes_and_the_single_prompt_limit(
        self, route_env, fake_llm, monkeypatch
    ):
        monkeypatch.setattr(service, "get_summarize_config", lambda _: SUMMARIZE)
        result = await routes.get_summary_sections(
            request=_request("/x"),
            doc_id=DOC_ID,
            data_source="wfp",
            model="gemini-2.5-flash",
            max_tokens=2000,
            admin=ADMIN,
        )
        assert result["has_section_types"] is True
        assert [s["section_type"] for s in result["sections"]] == [
            "executive_summary",
            "findings",
            "annexes",
        ]
        assert result["single_prompt"] == {
            "context_window": 100000,
            "available": True,
            "reason": None,
        }

    @pytest.mark.asyncio
    async def test_sections_refuse_a_model_outside_the_combos(self, route_env):
        with pytest.raises(HTTPException) as err:
            await routes.get_summary_sections(
                request=_request("/x"),
                doc_id=DOC_ID,
                data_source="wfp",
                model="some-other-model",
                max_tokens=2000,
                admin=ADMIN,
            )
        assert err.value.status_code == 400


class TestReprocess:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("replace", [True, False])
    async def test_reprocess_keeps_or_replaces_an_app_summary(
        self, monkeypatch, replace
    ):
        import sys
        from types import ModuleType

        from ui.backend.routes import documents as documents_routes

        updates: List[Dict[str, Any]] = []
        db = SimpleNamespace(
            get_document=lambda doc_id: {"id": doc_id, "sys_filepath": "/d.pdf"},
            delete_document_chunks=lambda doc_id: None,
            update_document=lambda doc_id, payload: updates.append(payload),
        )
        monkeypatch.setattr(documents_routes, "get_db_for_source", lambda _: db)
        task_module = ModuleType("pipeline.utilities.tasks")
        task_module.reprocess_document = SimpleNamespace(
            delay=lambda *args: SimpleNamespace(id="task-1")
        )
        monkeypatch.setitem(sys.modules, "pipeline.utilities.tasks", task_module)

        documents_routes.reprocess_document(
            DOC_ID, data_source="wfp", replace_summary=replace
        )

        (reset,) = updates
        assert reset["sys_status"] == "queued"
        if replace:
            assert reset[SUMMARY_USER_SET_FIELD] is False
        else:
            assert SUMMARY_USER_SET_FIELD not in reset
