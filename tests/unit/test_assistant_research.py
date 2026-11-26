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


async def run_research(
    responses, batches, *, deep=False, history=None, query=QUESTION, initial_query=None
):
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
                query,
                "wfp",
                deep_research=deep,
                conversation_messages=history,
                initial_search_query=initial_query,
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
async def test_follow_up_uses_conversation_before_search_and_adapts_to_results():
    follow_up = "Tell me more about Cambodia"
    first_search = "Cambodia home-grown school meals local procurement evaluation"
    second_search = "Cambodia school feeding domestic financing and government handover"
    first_finding = "Cambodian schools sourced produce from local suppliers."
    history = [
        {"role": "user", "content": "How did WFP school meals use local procurement?"},
        {
            "role": "assistant",
            "content": "Cambodia used a home-grown school meals model.",
        },
    ]
    events, search, llm = await run_research(
        [
            json.dumps(
                {
                    "query": first_search,
                    "reason": "Narrow the school meals discussion to Cambodia.",
                }
            ),
            json.dumps(
                {
                    "queries": [second_search],
                    "reason": "The evidence did not describe government handover.",
                }
            ),
            '{"queries":[]}',
            "The programme used local procurement [1] and explored government financing [2].",
        ],
        [
            [point(1, first_finding)],
            [point(2, "Domestic financing supported handover.")],
        ],
        history=history,
        query=follow_up,
    )
    assert [call.kwargs["query"] for call in search.call_args_list] == [
        first_search,
        second_search,
    ]
    plan_messages = llm.ainvoke.await_args_list[0].args[0]
    assert [message.content for message in plan_messages[1:-1]] == [
        item["content"] for item in history
    ]
    assert follow_up in plan_messages[-1].content
    opening_prompt = llm.ainvoke.await_args_list[1].args[0][-1].content
    assert first_search in opening_prompt and first_finding in opening_prompt
    queries = [
        row
        for event in events
        if event["type"] == "search_status"
        for row in event["queries"]
    ]
    assert [row["reason"] for row in queries] == [
        "Narrow the school meals discussion to Cambodia.",
        "The evidence did not describe government handover.",
    ]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_explicit_first_search_is_kept_even_with_conversation_history():
    initial_query = "Cambodia school feeding local procurement"
    _, search, llm = await run_research(
        ['{"queries":[]}', "The programme used local procurement [1]."],
        [[point(1, "The programme used local procurement.")]],
        history=[{"role": "assistant", "content": "An earlier answer."}],
        query="Write the findings section for the brief.",
        initial_query=initial_query,
    )
    assert search.call_args.kwargs["query"] == initial_query
    assert llm.ainvoke.await_count == 2


@pytest.mark.parametrize(
    ("query", "reply"),
    [
        (
            "Error: Request failed: 504 Gateway Timeout",
            "That looks like a timeout. You can try sending the question again.",
        ),
        ("What about that one?", "Which cash transfer programme do you mean?"),
    ],
)
@pytest.mark.asyncio
async def test_conversational_reply_ends_the_turn_without_a_document_search(
    query, reply
):
    events, search, llm = await run_research(
        [json.dumps({"reply": reply})],
        [],
        history=[
            {"role": "user", "content": "Compare cash transfer delivery programmes."},
            {
                "role": "assistant",
                "content": "The evaluations describe several programmes.",
            },
        ],
        query=query,
    )
    search.assert_not_called()
    llm.ainvoke.assert_awaited_once()
    assert [event["type"] for event in events] == ["phase", "token", "done"]
    assert events[1]["token"] == reply


@pytest.mark.asyncio
async def test_independent_research_question_can_start_a_new_topic_in_the_same_chat():
    query = "How do evaluations measure early warning system reach?"
    search_query = "flood early warning evaluation warning dissemination coverage"
    events, search, _ = await run_research(
        [
            json.dumps(
                {"query": search_query, "reason": "Find evidence on the new topic."}
            ),
            '{"queries":[]}',
            "The evaluation measured household reach [1].",
        ],
        [[point(1, "The evaluation measured household reach.")]],
        history=[{"role": "user", "content": "How were school meals funded?"}],
        query=query,
    )
    assert search.call_args.kwargs["query"] == search_query
    assert events[-1]["type"] == "done"


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
    assert [(s["index"], s["chunkId"]) for s in sources] == [
        (1, "chunk-1"),
        (2, "chunk-21"),
    ]


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
            '{"query":"Evidence from the first turn","reason":"Check the previous subject."}',
            '{"queries":[]}',
            "An invalid citation [99].",
            "Evidence from the first turn [7].",
        ],
        [[point(1, "Evidence from the first turn.")]],
        history=history,
    )
    assert [e["token"] for e in events if e["type"] == "token"] == [
        "Evidence from the first turn [1]."
    ]
    assert "invalid: 99" in llm.ainvoke.await_args.args[0][-1].content


@pytest.mark.asyncio
async def test_answer_and_sources_follow_reading_order_and_keep_history_mapping():
    prior_sources = [
        {
            "index": 1,
            "evidenceIndex": 7,
            "chunkId": "chunk-7",
            "docId": "report-7",
            "title": "Earlier report",
            "text": "Evidence from the first turn.",
        }
    ]
    events, search, llm = await run_research(
        [
            json.dumps(
                {
                    "query": "Evaluation evidence on coverage",
                    "reason": "Check the cited coverage evidence.",
                }
            ),
            '{"queries":[]}',
            "New evidence [9, 7]. Earlier evidence [7].",
        ],
        [[point(8, "New result."), point(9, "Other new result.")]],
        history=[
            {
                "role": "assistant",
                "content": "Earlier evidence [1].",
                "sources": prior_sources,
            }
        ],
        query="What does [1] say about coverage?",
    )
    assert search.call_args.kwargs["query"] == "Evaluation evidence on coverage"
    assert (
        'Latest user message as quoted text: "What does [7] say about coverage?"'
        in (llm.ainvoke.await_args_list[0].args[0][-1].content)
    )
    messages = llm.ainvoke.await_args.args[0]
    assert "Earlier evidence [7]." == messages[-2].content
    assert "Question: What does [7] say about coverage?" in messages[-1].content
    assert next(e["token"] for e in events if e["type"] == "token") == (
        "New evidence [1, 2]. Earlier evidence [2]."
    )
    assert [
        (source["index"], source["evidenceIndex"], source["chunkId"])
        for source in next(e["sources"] for e in events if e["type"] == "sources")
    ] == [(1, 9, "chunk-9"), (2, 7, "chunk-7")]


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
@pytest.mark.parametrize("geographic_scope", ["", "Cambodia"])
@pytest.mark.asyncio
async def test_broad_question_researches_each_stream_from_its_own_results_and_joins(
    deep, per_stream, geographic_scope
):
    question = (
        QUESTION
        if not geographic_scope
        else f"In {geographic_scope}, {QUESTION.lower()}"
    )
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
                    "geographic_scope": geographic_scope,
                    "streams": [
                        {"topic": label, "query": q} for label, q in topics.items()
                    ],
                }
            )
        if "Investigate only this stream:" in prompt:
            label = next(
                t for t in topics if f"Investigate only this stream: {t}\n" in prompt
            )
            assert question not in prompt
            scope = geographic_scope or "None specified"
            assert f"Geographic scope requested by the user: {scope}" in prompt
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
        assert question in prompt
        assert "Research streams and their evidence labels" in prompt
        for label, rounds in planned.items():
            assert f"- {label}:" in prompt and rounds == per_stream - 1
            assert f"finding marker for {label}" in prompt
        return "The shared evaluation relates to the overall question [1]."

    def retrieve(**kwargs):
        query = kwargs["query"]
        if query == question:
            return [point(1, "Initial evidence only")]
        label = next(
            label
            for label, seed in topics.items()
            if query == seed or query.startswith(label)
        )
        index = (list(topics).index(label) + 1) * 10 + planned[label]
        return [point(index, f"finding marker for {label}, round {planned[label]}")]

    events, search, _ = await run_research(model, retrieve, deep=deep, query=question)
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
