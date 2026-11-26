"""Exercise the Assistant workflow with actual LangGraph execution."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from ui.backend.services.assistant_service import stream_research_response

pytestmark = pytest.mark.unit
QUESTION = "What explains differences in malnutrition coverage and costs?"


def point(number, text):
    return SimpleNamespace(
        id=f"chunk-{number}",
        score=0.9,
        payload={
            "doc_id": f"report-{number}",
            "map_title": f"Report {number}",
            "text": text,
        },
    )


async def run_research(responses, batches, *, deep=False, history=None, query=QUESTION):
    llm = MagicMock()
    if callable(responses):
        llm.ainvoke = AsyncMock(
            side_effect=lambda messages, **kwargs: AIMessage(
                content=responses(messages)
            )
        )
    else:
        llm.ainvoke = AsyncMock(side_effect=[AIMessage(content=x) for x in responses])
    with (
        patch("ui.backend.utils.app_state.validate_data_source", return_value="wfp"),
        patch("ui.backend.services.assistant_service._get_llm", return_value=llm),
        patch(
            "ui.backend.services.assistant_service._get_trace_url", return_value=None
        ),
        patch(
            "ui.backend.services.assistant_service._trace_callbacks", return_value=[]
        ),
        patch(
            "ui.backend.services.assistant_graph.search_chunks", side_effect=batches
        ) as search,
        patch(
            "ui.backend.services.assistant_graph.SearchTracker._enrich_from_postgres"
        ),
        patch("ui.backend.services.assistant_graph.SearchTracker._enrich_doc_links"),
    ):
        events = [
            event
            async for event in stream_research_response(
                query, "wfp", deep_research=deep, conversation_messages=history
            )
        ]
    return events, search, llm


@pytest.mark.asyncio
async def test_assistant_starts_with_original_and_stops_when_evidence_is_sufficient():
    events, search, llm = await run_research(
        ['{"queries":[]}', "The evaluated sites reached 60% [1]."],
        [[point(1, "The evaluated sites reached 60%.")]],
    )
    assert [event["type"] for event in events] == [
        "phase",
        "phase",
        "plan",
        "search_status",
        "phase",
        "token",
        "sources",
        "done",
    ]
    assert search.call_args.kwargs["query"] == QUESTION
    assert llm.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_follow_up_is_based_on_results_and_writer_keeps_both_search_batches():
    follow_up = "Cost per cured individual and cost per beneficiary"
    initial = [point(1, "The evaluated sites reached 60%.")] + [
        point(i, f"Initial finding {i}.") for i in range(2, 21)
    ]
    events, search, llm = await run_research(
        [
            json.dumps({"queries": [QUESTION, follow_up]}),
            '{"queries":[]}',
            "Coverage was 60% [1]. The cost was $27.62 per cured individual [21].",
        ],
        [
            initial,
            [
                initial[0],
                point(21, "Annual cost was $27.62 per cured individual [^12]."),
            ],
        ],
    )
    assert [call.kwargs["query"] for call in search.call_args_list] == [
        QUESTION,
        follow_up,
    ]
    assert "reached 60%" in llm.ainvoke.await_args_list[0].args[0][-1].content
    writer = llm.ainvoke.await_args_list[-1].args[0][-1].content
    assert "[1] Report 1" in writer
    assert "[21] Report 21" in writer
    assert "[13] Report 13" not in writer
    assert "[^12]" not in writer
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert [s["index"] for s in sources] == list(range(1, 22))


@pytest.mark.parametrize(("deep", "budget"), [(False, 4), (True, 10)])
@pytest.mark.asyncio
async def test_research_modes_enforce_their_search_budgets(deep, budget):
    # Give each proposed search a substantially different vocabulary.
    queries = [
        json.dumps({"queries": [f"scenario{i} group{i} region{i} measure{i}"]})
        for i in range(budget - 1)
    ]
    events, search, llm = await run_research(
        [*queries, "There is evidence [1]."],
        [[point(i, f"Evidence {i}.")] for i in range(budget)],
        deep=deep,
    )
    assert search.call_count == budget
    assert llm.ainvoke.await_count == budget
    assert events[-1]["type"] == "done"
    planner = llm.ainvoke.await_args_list[0].args[0][0].content
    assert ("corroboration" in planner) is deep


@pytest.mark.asyncio
async def test_citation_revision_keeps_original_number_on_follow_up():
    history = [
        {
            "role": "assistant",
            "content": "Evidence from the first turn [7].",
            "sources": [
                {
                    "index": 7,
                    "chunkId": "chunk-1",
                    "docId": "report-1",
                    "title": "Report 1",
                    "text": "Evidence from the first turn.",
                }
            ],
        }
    ]
    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            "An invalid citation [99].",
            "Evidence from the first turn [7].",
        ],
        [[point(1, "Evidence from the first turn.")]],
        history=history,
    )
    assert [e["token"] for e in events if e["type"] == "token"] == [
        "Evidence from the first turn [7]."
    ]
    assert "invalid: 99" in llm.ainvoke.await_args.args[0][-1].content


@pytest.mark.asyncio
async def test_no_results_yields_an_evidence_gap_without_a_generated_answer():
    events, _, llm = await run_research(['{"queries":[]}'], [[]])
    assert "couldn’t find evidence" in next(
        e["token"] for e in events if e["type"] == "token"
    )
    assert llm.ainvoke.await_count == 1
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_retrieval_failure_returns_an_error_without_synthesis():
    events, _, llm = await run_research(
        [], [RuntimeError("private database information")]
    )
    assert events[-1] == {
        "type": "error",
        "error": "The Assistant could not complete this request.",
    }
    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_planner_reply_is_corrected_before_synthesis():
    events, search, llm = await run_research(
        ["I recommend stopping.", '{"queries":[]}', "Coverage was 60% [1]."],
        [[point(1, "Coverage was 60%.")]],
    )
    assert search.call_count == 1
    correction = llm.ainvoke.await_args_list[1].args[0][-1].content
    assert "previous reply did not match" in correction
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_repeated_invalid_planner_replies_fail_without_synthesis():
    events, search, llm = await run_research(
        ["I recommend stopping.", '{"queries":42}'],
        [[point(1, "Coverage was 60%.")]],
    )
    assert search.call_count == 1
    assert llm.ainvoke.await_count == 2
    assert [
        event["type"] for event in events if event["type"] in {"token", "done", "error"}
    ] == ["error"]


@pytest.mark.asyncio
async def test_planner_skips_a_reworded_search_when_it_has_another_option():
    first = (
        "What are the specific programme factors such as integration strategies and "
        "partnership models that consistently affect coverage and effectiveness "
        "across different malnutrition prevention and management approaches?"
    )
    similar = (
        "Which programme factors such as integration strategies and partnership models "
        "consistently affect coverage and effectiveness across different malnutrition "
        "prevention and management approaches?"
    )
    alternative = "Cost per beneficiary and cost per cured individual"
    _, search, _ = await run_research(
        [
            json.dumps({"queries": [first]}),
            json.dumps({"queries": [similar, alternative]}),
            '{"queries":[]}',
            "Coverage and costs are addressed [1, 3].",
        ],
        [[point(1, "Coverage")], [point(2, "Partnership")], [point(3, "Costs")]],
    )
    assert [call.kwargs["query"] for call in search.call_args_list] == [
        QUESTION,
        first,
        alternative,
    ]


@pytest.mark.parametrize(("deep", "per_stream"), [(False, 2), (True, 4)])
@pytest.mark.asyncio
async def test_broad_question_researches_each_stream_from_its_own_results_and_joins(
    deep, per_stream
):
    topics = {
        "Coverage": "community screening reach and service access",
        "Effectiveness": "recovery rates and reported treatment outcomes",
        "Cost-efficiency": "cost per beneficiary and cured individual",
        "Sustainability": "continued delivery and programme financing",
    }
    planned = {label: 0 for label in topics}

    def model(messages):
        prompt = messages[-1].content
        if "Initial evidence:" in prompt:
            return json.dumps(
                {
                    "streams": [
                        {"topic": label, "query": q} for label, q in topics.items()
                    ]
                }
            )
        if "Investigate only this stream:" in prompt:
            label = next(
                t for t in topics if f"Investigate only this stream: {t}\n" in prompt
            )
            assert QUESTION not in prompt
            assert f"Question: {topics[label]}" in prompt
            for other in topics:
                assert (f"finding marker for {other}" in prompt) is (other == label)
            attempt = planned[label]
            planned[label] += 1
            return json.dumps(
                {
                    "queries": [
                        f"{label} area{attempt} cohort{attempt} measure{attempt}"
                    ],
                    "reason": f"The latest {label} passage only covered one setting. "
                    + "The evidence describes delivery in one location. " * 8,
                }
            )
        assert QUESTION in prompt
        assert "Research streams and their evidence labels" in prompt
        for label, rounds in planned.items():
            assert f"- {label}:" in prompt and rounds == per_stream - 1
            assert f"finding marker for {label}" in prompt
        return "The shared evaluation relates to the overall question [1]."

    def retrieve(**kwargs):
        query = kwargs["query"]
        if query == QUESTION:
            return [point(1, "Initial evidence only")]
        label = next(
            label
            for label, seed in topics.items()
            if query == seed or query.startswith(label)
        )
        index = (list(topics).index(label) + 1) * 10 + planned[label]
        return [point(index, f"finding marker for {label}, round {planned[label]}")]

    events, search, _ = await run_research(model, retrieve, deep=deep)
    assert search.call_count == 1 + 4 * per_stream
    assert events[-1]["type"] == "done"
    assert len([e for e in events if e["type"] == "token"]) == 1
    searches = [
        row
        for event in events
        if event["type"] == "search_status"
        for row in event["queries"]
    ]
    for label in topics:
        stream = [row for row in searches if row["stream"] == label]
        assert len(stream) == per_stream
        assert stream[0]["query"] == topics[label]
        assert stream[-1]["reason"].startswith(
            f"The latest {label} passage only covered one setting."
        )
        assert len(stream[-1]["reason"]) <= 300
        assert stream[-1]["reason"].endswith("…")


@pytest.mark.asyncio
async def test_similar_stream_seeds_need_a_new_plan_before_searching():
    seeds = [
        {
            "topic": "Coverage",
            "query": (
                "malnutrition programme factors sustainability "
                "cost-efficiency effectiveness coverage"
            ),
        },
        {
            "topic": "Effectiveness",
            "query": (
                "malnutrition prevention effectiveness sustainability cost-efficiency "
                "contextual factors coverage programme"
            ),
        },
    ]
    events, search, llm = await run_research(
        [json.dumps({"streams": seeds}), '{"queries":[]}', "Evidence [1]."],
        [[point(1, "Evidence")]],
    )
    assert search.call_count == 1
    assert events[-1]["type"] == "done"
    assert (
        "previous reply did not match"
        in llm.ainvoke.await_args_list[1].args[0][-1].content
    )
