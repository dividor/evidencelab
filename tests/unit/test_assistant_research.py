"""Exercise the Assistant workflow with actual LangGraph execution."""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from ui.backend.auth.schemas import BriefSectionPrompt
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
    responses,
    batches,
    *,
    deep=False,
    history=None,
    query=QUESTION,
    initial_query=None,
    supported=True,
    check=None,
    scope_check=None,
    select_evidence=None,
    find_duplicates=None,
    prose=None,
    brief_section_prompt=None,
    brief_section=None,
    survey_only=False,
    check_citations=True,
    system_prompt_override=None,
    target_words=None,
):
    llm = MagicMock()
    replies = None if callable(responses) else iter(responses)

    def model(messages, **kwargs):
        if messages[0].content.startswith("Edit a report section for repetition"):
            prompt = messages[-1].content
            rows = [
                {"id": label, "text": text}
                for label, text in json.loads(prompt)["new_section"]
            ]
            duplicates = find_duplicates(rows) if find_duplicates else []
            return AIMessage(content=json.dumps({"duplicates": duplicates}))
        if messages[0].content.startswith("Select passages that directly support"):
            prompt = messages[-1].content
            labels = [
                int(label) for label in re.findall(r"(?m)^Passage \[(\d+)\]$", prompt)
            ]
            selected = (
                select_evidence(prompt, labels)
                if select_evidence
                else [
                    {
                        "citation": label,
                        "subject_line": 1,
                        "finding_lines": _fixture_source_lines(prompt, label),
                    }
                    for label in labels
                ]
            )
            return AIMessage(
                content=json.dumps({"section_subject": query, "passages": selected})
            )
        if messages[0].content.startswith("Decide which of the proposed sentences"):
            prompt = messages[-1].content
            rows = json.loads(prompt.split("Sentences: ", 1)[1].splitlines()[0])
            reviews = (
                scope_check(prompt, rows)
                if scope_check
                else [
                    {
                        "id": row["id"],
                        "subject": "the subject of this section",
                        "reason": "The finding matches the section.",
                        "keep": True,
                    }
                    for row in rows
                ]
            )
            return AIMessage(
                content=json.dumps(
                    {
                        "reviews": [
                            {
                                "covers_other_heading": False,
                                "source_matches_assignment": True,
                                "unsupported_phrases": [],
                                **row,
                            }
                            for row in reviews
                        ]
                    }
                )
            )
        if messages[0].content.startswith("Review whether this proposed Brief"):
            issues = prose(messages[-1].content) if prose is not None else []
            return AIMessage(content=json.dumps({"issues": issues}))
        if messages[0].content.startswith("Check whether the proposed answer"):
            prompt = messages[-1].content
            if check is not None:
                return AIMessage(content=json.dumps(check(prompt)))
            rows = _review_rows(prompt)
            excerpts = dict(re.findall(r"(?m)^\[(\d+)\] [^\n]+\n([^\n]+)", prompt))
            checks = [
                {
                    "id": row["id"],
                    "status": "supported" if supported else "unsupported",
                    "quotes": (
                        [
                            {"citation": index, "quote": excerpts[str(index)]}
                            for index in row["citations"]
                        ]
                        if supported
                        else []
                    ),
                }
                for row in rows
            ]
            return AIMessage(
                content=json.dumps({"scope_issues": [], "sentences": checks})
            )
        reply = responses(messages) if replies is None else next(replies)
        if messages[0].content.startswith("Write the prose of one section"):
            reply = _fixture_excerpt_labels(reply, messages[-1].content)
        return AIMessage(content=reply)

    llm.ainvoke = AsyncMock(side_effect=model)
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
                brief_section_prompt=brief_section_prompt,
                brief_section=brief_section,
                survey_only=survey_only,
                check_citations=check_citations,
                system_prompt_override=system_prompt_override,
                target_words=target_words,
            )
        ]
    return events, search, llm


@pytest.mark.asyncio
@pytest.mark.parametrize("follow_up", [False, True])
async def test_outline_survey_when_research_finishes_then_only_sources_are_returned(
    follow_up,
):
    plans = ['{"queries":[]}']
    batches = [[point(1, "School registers record enrolment.")]]
    if follow_up:
        plans[0] = (
            '{"queries":["Reasons pupils leave school"],"reason":"The register omits reasons."}'
        )
        plans.append('{"queries":[]}')
        batches.append([point(2, "School fees affected attendance.")])
    events, search, llm = await run_research(
        plans, batches, query="School attendance", deep=False, survey_only=True
    )

    assert search.call_count == len(batches)
    assert llm.ainvoke.await_count == len(plans)
    assert not any(event["type"] in {"token", "error"} for event in events)
    assert not any(
        event.get("phase") in {"synthesizing", "checking_citations"} for event in events
    )
    assert len(
        next(event["sources"] for event in events if event["type"] == "sources")
    ) == len(batches)
    assert events[-1]["type"] == "done"


def _review_rows(prompt):
    return json.loads(prompt.split("Sentences to check: ", 1)[1].splitlines()[0])


def _fixture_source_lines(prompt, label):
    passage = prompt.split(f"Passage [{label}]\n", 1)[1].split("\n\nPassage [", 1)[0]
    return [int(n) for n in re.findall(r"(?m)^([1-9]\d*): ", passage)]


def _fixture_excerpt_labels(reply, prompt):
    """Select the fixture's requested quote from the excerpts actually supplied."""
    labels = {}
    source = None
    for line in prompt.splitlines():
        if heading := re.match(r"Source (\d+): ", line):
            source = heading[1]
        if excerpt := re.match(r"\[(\d+)\] (.+)", line):
            labels[excerpt[1]] = (source, excerpt[2])

    def label(match):
        for index, (passage, line) in labels.items():
            if passage == match[1] and match[2].lower() in line.lower():
                return f"[{index}]"
        return "[99999]"

    return re.sub(r"\[\[(\d+)\|(.+?)\]\]", label, reply)


def _brief_draft(*findings, limit=""):
    prose = " ".join(
        f"{text.rstrip('.')} [[{citation}|{quote}]]."
        for text, citation, quote in findings
    )
    return f"{prose}\n\nLimit: {limit}" if limit else prose


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
        "phase",
        "token",
        "sources",
        "done",
    ]
    assert search.call_args.kwargs["query"] == QUESTION
    assert llm.ainvoke.await_count == 3


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
    assert llm.ainvoke.await_count == 3


@pytest.mark.parametrize(
    ("query", "action", "message"),
    [
        (
            "Tell me more about Santa Claus",
            "decline",
            "I can only answer questions supported by the documents in my library.",
        ),
        (
            "What about that one?",
            "clarify",
            "What would you like me to look up in the selected dataset?",
        ),
    ],
)
@pytest.mark.asyncio
async def test_out_of_scope_or_ambiguous_follow_up_uses_a_fixed_dataset_message(
    query, action, message
):
    events, search, llm = await run_research(
        [json.dumps({"action": action})],
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
    assert events[1]["token"].startswith(message)


@pytest.mark.asyncio
async def test_the_old_free_form_reply_is_never_shown():
    events, search, _ = await run_research(
        ['{"reply":"Santa Claus is a legendary figure."}', '{"action":"decline"}'],
        [],
        history=[{"role": "user", "content": "How did WFP deliver cash transfers?"}],
        query="Tell me more about Santa Claus",
    )
    search.assert_not_called()
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer.startswith(
        "I can only answer questions supported by the documents in my library."
    )


@pytest.mark.asyncio
async def test_repeated_refusal_changes_its_next_step_without_answering_the_question():
    reply = "I can only answer questions supported by the documents in my library. "
    history = [
        {
            "role": "assistant",
            "content": reply + "What would you like to find in those documents?",
        }
    ]
    events, search, _ = await run_research(
        ['{"action":"decline","next_step":"ask"}'],
        [],
        history=history,
        query="But why not Santa?",
    )
    search.assert_not_called()
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer.startswith(reply)
    assert answer != history[0]["content"]


@pytest.mark.asyncio
async def test_brief_search_planning_is_scoped_and_only_the_writer_gets_the_full_outline():
    heading = "Use of social and behavioural change in school meals"
    follow_up = (
        "WFP school meals evaluations report portfolio coverage of SBC components"
    )
    excluded_heading = "Attendance and learning outcomes"
    guidance = "Find the share of programmes with an SBC component."
    other_question = "Which interventions improved school attendance?"
    brief_section = BriefSectionPrompt(
        outline=[{"title": heading}, {"title": excluded_heading}],
        current=0,
        instructions=f"Give the evidence gaps.\n1. {guidance}\n2. {other_question}",
        focus="Check for a portfolio-wide denominator.",
    )
    answer = "The evaluation found SBC in three of the programmes it reviewed [1]."
    events, search, llm = await run_research(
        [
            json.dumps({"selected": [1]}),
            json.dumps(
                {
                    "queries": [follow_up],
                    "reason": "Look for the portfolio denominator.",
                }
            ),
            '{"queries":[]}',
            _brief_draft(
                (answer.split(" [1]")[0], 1, "Three reviewed programmes used SBC")
            ),
        ],
        [[point(1, "Three reviewed programmes used SBC.")], []],
        deep=True,
        query=heading,
        initial_query=heading,
        brief_section_prompt="Write a grounded section of the brief.",
        brief_section=brief_section,
        system_prompt_override="The Search AI Summary prompt requires every source finding.",
    )
    assert [call.kwargs["query"] for call in search.call_args_list] == [
        heading,
        follow_up,
    ]
    scope, opening, next_search, selection, writer, scope_verifier, verifier = [
        call.args[0][-1].content for call in llm.ainvoke.await_args_list
    ]
    assert excluded_heading in scope and other_question in scope
    for planning in (opening, next_search):
        assert heading in planning and guidance in planning
        assert excluded_heading not in planning
        assert brief_section.focus in planning
    assert guidance in writer and excluded_heading in writer
    assert guidance in selection and excluded_heading in selection
    assert heading in scope_verifier and excluded_heading in scope_verifier
    assert (
        "Search AI Summary prompt"
        not in llm.ainvoke.await_args_list[4].args[0][0].content
    )
    assert other_question not in writer and other_question not in verifier
    assert (
        next(event["token"] for event in events if event["type"] == "token") == answer
    )


@pytest.mark.asyncio
async def test_brief_update_revises_extra_headings_with_citation_check_off():
    def prose(prompt):
        return (
            ["Remove the extra title and labels."] if "Main findings" in prompt else []
        )

    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            "## Main findings ##\n\nAccess\n------\n\nSchool sites had better access [1].",
            "School sites had better access [1].",
        ],
        [[point(1, "School sites had better access.")]],
        brief_section_prompt="Explain the evaluation findings in plain language.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Programme access"}], current=0, mode="update"
        ),
        initial_query="Programme access in schools",
        check_citations=False,
        prose=prose,
    )
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer == "School sites had better access [1]."


@pytest.mark.asyncio
async def test_brief_opening_repair_uses_sources_and_keeps_length_and_voice():
    good = "The evaluation found that school sites had better access [1]."
    draft = "The programme substantially improved many outcomes. " + good
    events, _, llm = await run_research(
        ['{"queries":[]}', draft, good],
        [[point(1, "School sites had better access.")]],
        initial_query="Access in schools",
        brief_section_prompt="Use evaluation evidence for the assigned section.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Access in schools"}],
            current=0,
            mode="update",
            voice_instructions="Use plain British English and neutral evaluation language.",
        ),
        check_citations=False,
        target_words=350,
    )
    assert next(event["token"] for event in events if event["type"] == "token") == good
    revised = llm.ainvoke.await_args_list[-2].args[0]
    assert "approximately 350 words" in revised[0].content
    assert (
        "plain British English and neutral evaluation language" in revised[-1].content
    )
    assert (
        "opening sentence needs a finding supported by a citation"
        in revised[-1].content
    )


@pytest.mark.asyncio
async def test_brief_generation_keeps_sourced_prose_with_citation_check_off():
    finding = "The rollout reached four of the six test sites"
    evidence = finding + "."
    events, _, model = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                ("The rollout reached every site", 1, "every site"),
                (finding, 1, "four of the six test sites"),
            ),
        ],
        [[point(1, evidence)]],
        initial_query="Rollout coverage",
        brief_section_prompt="Summarize the reported rollout coverage.",
        brief_section=BriefSectionPrompt(outline=[{"title": "Coverage"}], current=0),
        check_citations=False,
    )
    assert events[-1]["section_written"] is True
    assert next(event["token"] for event in events if event["type"] == "token") == (
        finding + " [1]."
    )
    assert not any(event.get("phase") == "checking_citations" for event in events)
    assert model.ainvoke.await_count == 3


@pytest.mark.parametrize(
    "claim",
    [
        "Santa Claus was inspired by Saint Nicholas.",
        "Santa Claus was inspired by Saint Nicholas [1].",
    ],
)
@pytest.mark.asyncio
async def test_unsupported_answer_is_withheld_even_if_it_names_a_valid_citation(claim):
    events, _, llm = await run_research(
        ['{"queries":[]}', claim, claim],
        [[point(1, "The WFP report described school meals.")]],
        query="Tell me about Santa Claus",
        supported=False,
    )
    assert "couldn’t find evidence" in next(
        event["token"] for event in events if event["type"] == "token"
    )
    assert not any(event["type"] == "sources" for event in events)
    if claim.endswith("[1]."):
        verification = llm.ainvoke.await_args.args[0][-1].content
        assert claim in verification
        assert "The WFP report described school meals." in verification


@pytest.mark.asyncio
async def test_citation_checker_withholds_bad_claim_and_only_streams_verified_rewrite():
    erroneous = "The pilot reached 90 percent of schools [1]."
    corrected = "The pilot reached 60 percent of schools [1]."

    def judge(prompt):
        row = _review_rows(prompt)[0]
        number = 90 if erroneous == row["text"] else 60
        return {
            "scope_issues": [],
            "sentences": [
                {
                    "id": row["id"],
                    "status": "supported",
                    "quotes": [
                        {
                            "citation": 1,
                            "quote": f"reached {number} percent of schools",
                        },
                    ],
                }
            ],
        }

    events, search, llm = await run_research(
        ['{"queries":[]}', erroneous, corrected],
        [[point(1, "The pilot reached 60 percent of schools.")]],
        check=judge,
    )
    assert search.call_count == 1
    assert [event["token"] for event in events if event["type"] == "token"] == [
        corrected
    ]
    rewrite = llm.ainvoke.await_args_list[-2].args[0][-1].content
    assert "Sentence 1 lacks verified quotes from [1]" in rewrite


@pytest.mark.asyncio
async def test_assistant_keeps_the_verified_finding_without_an_extra_writer_call():
    first = "The pilot reached 60 percent of schools [1]."
    last = "The survey ran in June [1]."
    draft = (
        "## Coverage\n\n" + first + "\n\n## Attendance\n\n"
        "The programme doubled attendance.\n\n## Evaluation dates\n\n" + last
    )

    def judge(prompt):
        ids = {row["id"] for row in _review_rows(prompt)}
        verdicts = [
            {
                "id": 2,
                "status": "supported",
                "quotes": [{"citation": 1, "quote": "reached 60 percent of schools"}],
            },
            {
                "id": 4,
                "status": "unsupported",
                "quotes": [],
                "issue": "Attendance was not reported.",
            },
            {
                "id": 6,
                "status": "supported",
                "quotes": [{"citation": 1, "quote": "survey ran in June"}],
            },
            *[
                {"id": index, "status": "non_factual", "quotes": []}
                for index in (1, 3, 5)
            ],
        ]
        return {
            "scope_issues": [],
            "sentences": [row for row in verdicts if row["id"] in ids],
        }

    events, _, llm = await run_research(
        ['{"queries":[]}', draft],
        [
            [
                point(
                    1,
                    "The pilot reached 60 percent of schools. The survey ran in June.",
                )
            ]
        ],
        check=judge,
    )
    assert [event["token"] for event in events if event["type"] == "token"] == [
        "## Coverage\n\n" + first + "\n\n## Evaluation dates\n\n" + last
    ]
    assert llm.ainvoke.await_count == 4


@pytest.mark.asyncio
async def test_assistant_streams_only_what_the_checker_retained_even_without_issues():
    excerpt = "The pilot reached 60 percent of schools."
    answer = (
        "## Coverage\n\nDelivery expanded sharply. "
        "The pilot reached 60 percent of schools [1]."
    )

    def judge(prompt):
        return {
            "scope_issues": [],
            "sentences": [
                {
                    "id": row["id"],
                    "status": "supported" if row["citations"] else "non_factual",
                    "quotes": (
                        [{"citation": 1, "quote": excerpt}] if row["citations"] else []
                    ),
                }
                for row in _review_rows(prompt)
            ],
        }

    events, _, _ = await run_research(
        ['{"queries":[]}', answer], [[point(1, excerpt)]], check=judge
    )

    assert next(e["token"] for e in events if e["type"] == "token") == (
        "## Coverage\n\nThe pilot reached 60 percent of schools [1]."
    )


@pytest.mark.asyncio
async def test_disabling_citation_check_only_skips_the_semantic_review():
    answer = "The programme reached 60 percent of schools [1]."
    events, _, llm = await run_research(
        ['{"queries":[]}', "The programme reached 60 percent [99].", answer],
        [[point(1, "The programme reached 60 percent of schools.")]],
        check_citations=False,
    )
    assert [event["token"] for event in events if event["type"] == "token"] == [answer]
    assert llm.ainvoke.await_count == 3
    assert "invalid: 99" in llm.ainvoke.await_args.args[0][-1].content


@pytest.mark.asyncio
async def test_brief_keeps_its_verified_findings_and_qualified_evidence_gap():
    finding = (
        "The evaluation documented social and behavioural change in school meals [1]."
    )
    gap = (
        "The evaluations reviewed here do not establish the share of programmes "
        "with this component."
    )
    draft = (
        _brief_draft(
            (
                finding.split(" [1]")[0],
                1,
                "documented social and behavioural change in school meals",
            ),
            (
                "Enrolment doubled",
                1,
                "documented social and behavioural change in school meals",
            ),
            ("Attendance doubled", 1, "attendance rates doubled in 2025"),
            ("Every school used the intervention", [1, 2], None),
            (
                "The other section covers attendance",
                1,
                "documented social and behavioural change",
            ),
            limit=gap,
        )
        + '\n{"text": "This record was cut off"'
    )

    def judge(prompt):
        assert len(_review_rows(prompt)) == 3
        assert (
            "documented social and behavioural change in school meals"
            in _review_rows(prompt)[0]["prepared_quotes"][0]["quote"]
        )
        return {
            "scope_issues": [],
            "sentences": [
                {
                    "id": 1,
                    "status": "supported",
                    "quotes": [],
                },
                {
                    "id": 2,
                    "status": "unsupported",
                    "quotes": [],
                    "issue": "This belongs in the education section.",
                },
                {"id": 3, "status": "evidence_gap", "quotes": []},
            ],
        }

    events, _, llm = await run_research(
        ['{"queries":[]}', draft],
        [
            [
                point(
                    1,
                    "The evaluation documented social and behavioural change in school meals.",
                ),
                point(2, "The report summarizes teacher staffing levels."),
            ]
        ],
        query="How many programmes used social and behavioural change?",
        initial_query="Social and behavioural change in school meals",
        brief_section_prompt="Describe the evidence for this section only.",
        brief_section=BriefSectionPrompt(
            outline=[
                {"title": "Extent of SBC"},
                {
                    "title": "Education",
                    "content": "The other section covers attendance [2].",
                },
            ],
            current=0,
        ),
        check=judge,
    )
    assert [event["token"] for event in events if event["type"] == "token"] == [
        finding + "\n\n" + gap
    ]
    assert llm.ainvoke.await_count == 6
    comparison = llm.ainvoke.await_args.args[0][-1].content
    assert "The other section covers attendance" in comparison
    assert events[-1]["section_written"] is True
    sources = next(event["sources"] for event in events if event["type"] == "sources")
    assert [source["chunkId"] for source in sources] == ["chunk-1"]


@pytest.mark.asyncio
async def test_brief_revises_a_short_draft_as_one_paragraph_and_rechecks_each_sentence():
    first = "In Armenia, teachers delivered nutrition education."
    lead = "For example, in Armenia, teachers delivered nutrition education."
    second = "In Malawi, students learned safe food preparation."
    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (
                    lead,
                    1,
                    "teachers delivered nutrition education",
                )
            ),
            _brief_draft(
                (first, 1, "teachers delivered nutrition education"),
                (second, 2, "students learned safe food preparation"),
            ),
        ],
        [[point(1, first), point(2, second)]],
        initial_query="Nutrition and hygiene learning in school meal programmes",
        brief_section_prompt="Report independent findings without extra headings.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Nutrition education"}], current=0
        ),
        target_words=100,
    )
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer == f"{first.rstrip('.')} [1]. {second.rstrip('.')} [2]."
    assert len(answer.split()) <= 100
    drafts = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert len(drafts) == 2 and "complete revised section" in drafts[-1]
    assert lead in drafts[-1]
    verdict_requests = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Check whether the proposed answer")
    ]
    rows = _review_rows(verdict_requests[-1])
    assert [row["text"] for row in rows] == [
        f"{first.rstrip('.')} [1].",
        f"{second.rstrip('.')} [2].",
    ]
    assert rows[1]["preceding_sentence"] == rows[0]["text"]


@pytest.mark.asyncio
async def test_brief_keeps_the_checked_draft_when_revision_yields_less_evidence():
    first = "Pressure returned to normal after the valve was repaired"
    second = "The system then ran continuously for six hours"
    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft((first, 1, first), (second, 1, second)),
            _brief_draft((first, 1, first)),
        ],
        [[point(1, f"{first}. {second}.")]],
        brief_section=BriefSectionPrompt(outline=[{"title": "Recovery"}], current=0),
        target_words=150,
    )
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer == f"{first} [1]. {second} [1]."


@pytest.mark.asyncio
async def test_brief_attempts_more_detail_when_four_findings_are_too_short():
    findings = [
        "The programme operated in three districts",
        "The evaluation surveyed forty school leaders",
        "Teachers adapted lesson plans for returning students",
        "School attendance was tracked monthly",
        "Attendance data informed the allocation of teaching assistants",
    ]
    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(*((finding, 1, finding) for finding in findings[:4])),
            _brief_draft(*((finding, 1, finding) for finding in findings)),
        ],
        [[point(1, ". ".join(findings) + ".")]],
        initial_query="School reintegration evaluation",
        brief_section_prompt="Describe the programme evaluation.",
        brief_section=BriefSectionPrompt(outline=[{"title": "Evaluation"}], current=0),
        target_words=350,
    )

    answer = next(event["token"] for event in events if event["type"] == "token")
    assert all(finding in answer for finding in findings)
    drafts = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert (
        len(drafts) == 2
        and "24 words. The target for the complete section is 350 words" in drafts[-1]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quote", "draft", "shown"),
    [
        ("Attendance improved", "Attendance improved (1)", "Attendance improved"),
        ("The rating was 1", "The rating was (1)", "The rating was (1)"),
    ],
)
async def test_brief_writes_one_citation_and_preserves_quoted_numbers(
    quote, draft, shown
):
    events, _, _ = await run_research(
        ['{"queries":[]}', _brief_draft((draft, 1, quote))],
        [[point(1, quote + ".")]],
        brief_section=BriefSectionPrompt(outline=[{"title": "Attendance"}], current=0),
    )

    assert next(event["token"] for event in events if event["type"] == "token") == (
        shown + " [1]."
    )


@pytest.mark.asyncio
async def test_brief_researches_separate_outcomes_within_one_section():
    heading = "Continuity and recovery after the equipment upgrade"
    scope = "Report interruptions and restart times separately. Leave costs to the next section."
    interruptions = (
        "Two service interruptions were recorded after the equipment upgrade"
    )
    restart = "The equipment restarted within six seconds"
    plan = json.dumps(
        {
            "streams": [
                {
                    "topic": "Continuity",
                    "query": "Recorded service interruptions after upgrade",
                },
                {"topic": "Recovery", "query": "Equipment restart times after upgrade"},
            ],
            "geographic_scope": "",
        }
    )
    events, search, llm = await run_research(
        [
            plan,
            '{"queries":[]}',
            '{"queries":[]}',
            _brief_draft((interruptions, 2, interruptions), (restart, 3, restart)),
        ],
        [
            [point(1, "The report recorded several upgrade outcomes.")],
            [point(2, interruptions + ".")],
            [point(3, restart + ".")],
        ],
        query=heading,
        deep=True,
        brief_section=BriefSectionPrompt(
            topic="Equipment after a firmware upgrade",
            outline=[
                {"title": heading},
                {"title": "Continuity", "level": 2},
                {"title": "Recovery", "level": 2},
                {"title": "Costs"},
            ],
            current=0,
            focus=scope,
        ),
    )
    opening = llm.ainvoke.await_args_list[0].args[0]
    assert "streams format" in opening[0].content
    assert scope in opening[-1].content
    planning = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if "Initial evidence:" in call.args[0][-1].content
        or "Searches remaining:" in call.args[0][-1].content
    ]
    assert len(planning) == 3
    for request in planning:
        assert 'Subheadings introduced here: ["Continuity", "Recovery"]' in request
        assert 'Brief topic: "Equipment after a firmware upgrade"' in request
        assert f'Assigned heading: "{heading}"' in request
    assert search.call_count == 3
    assert events[-1]["section_written"] is True


@pytest.mark.asyncio
async def test_brief_uses_one_ranked_follow_up_when_model_lists_more_than_three():
    opening = "Evidence on school reintegration"
    first = "School reintegration barriers documented by evaluations"
    best = "Language support for students returning from migration"
    finding = "Schools provided language support to returning students"
    events, search, llm = await run_research(
        [
            '{"queries":[]}',
            json.dumps(
                {"queries": [first], "reason": "Find which barriers were observed."}
            ),
            json.dumps(
                {
                    "queries": [
                        first,
                        best,
                        "Access to school counselling",
                        "Training materials for teachers",
                    ],
                    "reason": "Find specific help offered to returning students.",
                }
            ),
            '{"queries":[]}',
            _brief_draft((finding, 3, finding)),
        ],
        [
            [point(1, "Returnees faced barriers to school.")],
            [point(2, "School records showed gaps after migration.")],
            [point(3, finding + ".")],
        ],
        deep=True,
        initial_query=opening,
        brief_section_prompt="Describe the support offered.",
        brief_section=BriefSectionPrompt(outline=[{"title": "Support"}], current=0),
    )

    assert [call.kwargs["query"] for call in search.call_args_list] == [
        opening,
        first,
        best,
    ]
    draft_request = next(
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    )
    assert draft_request.index(finding) < draft_request.index(
        "Returnees faced barriers to school."
    )
    assert events[-1]["section_written"] is True
    assert next(e["token"] for e in events if e["type"] == "token") == finding + " [1]."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_draft", "issue"),
    [
        (
            "Teachers reported vocabulary barriers [99999].",
            "Cite a numbered excerpt",
        ),
        (
            json.dumps({"paragraph": 1, "text": "An entire paragraph. " * 35}),
            "Cite a numbered excerpt",
        ),
        (
            json.dumps(
                {"paragraph": 1, "text": "The trial was inconclusive.", "limit": True}
            ),
            "Cite a numbered excerpt",
        ),
    ],
)
async def test_brief_describes_the_format_error_and_retries(invalid_draft, issue):
    finding = "Teachers reported limited vocabulary as a barrier to classroom learning"
    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            invalid_draft,
            _brief_draft((finding, 1, finding)),
        ],
        [[point(1, finding + ".")]],
        initial_query="Language barriers in the classroom",
        brief_section_prompt="Report what teachers observed.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Language barriers"}], current=0
        ),
    )

    first_request, retry_request = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert "Return only the finished prose" not in first_request
    assert (
        "Cite each factual sentence before its final punctuation" not in first_request
    )
    assert issue in retry_request
    assert events[-1]["section_written"] is True
    assert next(e["token"] for e in events if e["type"] == "token") == finding + " [1]."


@pytest.mark.asyncio
async def test_brief_recovers_the_opening_citation_in_its_original_paragraph():
    opening = "The inspection found a leak"
    detail = "The seal had cracked at the joint"
    raw = opening + ". " + _brief_draft((detail, 2, detail))
    corrected = _brief_draft((opening, 1, opening), (detail, 2, detail))
    events, _, model = await run_research(
        ['{"queries":[]}', raw, corrected],
        [[point(1, opening + "."), point(2, detail + ".")]],
        brief_section=BriefSectionPrompt(outline=[{"title": "Inspection"}], current=0),
    )
    requests = [
        call.args[0][-1].content
        for call in model.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert len(requests) == 2
    assert f'Draft to correct: "{opening}. {detail}' in requests[1]
    assert next(e["token"] for e in events if e["type"] == "token") == (
        f"{opening} [1]. {detail} [2]."
    )


@pytest.mark.asyncio
async def test_brief_excludes_a_midterm_finding_misattributed_to_endline():
    source = point(1, "Students reported improved hygiene at midterm.")
    source.payload["map_title"] = "Mid-Term Evaluation of school meals in Laos"
    draft = _brief_draft(
        (
            "The endline evaluation found that students reported improved hygiene",
            1,
            "students reported improved hygiene",
        ),
        (
            "The midterm evaluation found that students reported improved hygiene",
            1,
            "students reported improved hygiene",
        ),
    )
    events, _, _ = await run_research(
        ['{"queries":[]}', draft],
        [[source]],
        initial_query="School meals hygiene results",
        brief_section_prompt="Report the evidence on student hygiene.",
        brief_section=BriefSectionPrompt(outline=[{"title": "Hygiene"}], current=0),
    )
    assert next(event["token"] for event in events if event["type"] == "token") == (
        "The midterm evaluation found that students reported improved hygiene [1]."
    )


@pytest.mark.asyncio
async def test_brief_uses_ordinary_documents_without_place_or_study_metadata():
    source = point(1, "The release checklist requires two reviewers before deployment.")
    source.payload["map_title"] = "Release checklist"
    finding = "The release checklist requires two reviewers before deployment"
    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (
                    "Every deployment must have two reviewers [2].",
                    1,
                    "requires two reviewers before deployment",
                ),
                (f"{finding} [1].", 1, "requires two reviewers before deployment"),
            ),
        ],
        [[source]],
        initial_query="Release approval requirements",
        brief_section_prompt="Summarize the release requirements using the documents.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Release approvals"}], current=0
        ),
    )
    assert events[-1]["section_written"] is True
    assert next(event["token"] for event in events if event["type"] == "token") == (
        finding + " [1]."
    )
    assert [
        s["title"] for s in next(e["sources"] for e in events if e["type"] == "sources")
    ] == ["Release checklist"]


@pytest.mark.asyncio
async def test_brief_checks_paraphrases_against_findings_in_other_sections():
    earlier = "The release checklist requires two reviewers before deployment"
    repeated = "Before deployment, the release checklist requires two reviewers"
    distinct = "Each release must include an executable rollback procedure"
    outline = [
        {"title": "Approval", "content": earlier + " [7]."},
        {"title": "Rollback"},
    ]

    def review(prompt):
        duplicate, new_finding = _review_rows(prompt)
        assert duplicate["similar_findings"] == [
            {"heading": "Approval", "finding": earlier + "."}
        ]
        assert "similar_findings" not in new_finding
        return {
            "scope_issues": [],
            "sentences": [
                {"id": 1, "status": "unsupported", "issue": "Already in Approval."},
                {"id": 2, "status": "supported"},
            ],
        }

    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (repeated, 1, "requires two reviewers before deployment"),
                (distinct, 1, "include an executable rollback procedure"),
            ),
        ],
        [[point(1, earlier + ". " + distinct + ".")]],
        initial_query="Release rollback requirements",
        brief_section_prompt="Summarize the rollback requirements using the documents.",
        brief_section=BriefSectionPrompt(outline=outline, current=1),
        check=review,
    )
    assert events[-1]["section_written"] is True
    assert next(event["token"] for event in events if event["type"] == "token") == (
        distinct + " [1]."
    )


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
    writer = llm.ainvoke.await_args_list[-2].args[0][-1].content
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
        json.dumps(
            {
                "queries": [f"scenario{i} group{i} region{i} measure{i}"],
                "reason": "Corroborate the current finding.",
            }
        )
        for i in range(budget - 1)
    ]
    events, search, llm = await run_research(
        [*queries, "There is evidence [1]."],
        [[point(i, f"Evidence {i}.")] for i in range(budget)],
        deep=deep,
    )
    assert search.call_count == budget
    assert llm.ainvoke.await_count == budget + 1
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
                    "dataSource": "wfp",
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
    assert "invalid: 99" in llm.ainvoke.await_args_list[-2].args[0][-1].content


@pytest.mark.asyncio
async def test_answer_and_sources_follow_reading_order_and_keep_history_mapping():
    prior_sources = [
        {
            "index": 1,
            "evidenceIndex": 7,
            "chunkId": "chunk-7",
            "docId": "report-7",
            "dataSource": "wfp",
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
    messages = llm.ainvoke.await_args_list[-2].args[0]
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
async def test_brief_with_unverified_prose_completes_without_a_draft_or_sources():
    draft = _brief_draft(("Enrolment doubled", 1, "reviewed school meals"))
    events, _, _ = await run_research(
        ['{"queries":[]}', draft, draft],
        [[point(1, "The evaluation reviewed school meals.")]],
        initial_query="School meals",
        brief_section_prompt="Describe the evidence for this section.",
        brief_section=BriefSectionPrompt(outline=[{"title": "Enrolment"}], current=0),
        supported=False,
    )
    assert not any(
        event["type"] in {"sources", "token", "brief_section_unwritten"}
        for event in events
    )
    assert events[-1]["type"] == "done"
    assert events[-1]["section_written"] is False


@pytest.mark.asyncio
async def test_brief_update_final_repair_keeps_supported_finding_and_restores_review_limit():
    finding = "The evaluation documented nutrition education in school meals [1]."
    mixed = "Programme use was widespread, but the reviewed evaluations did not give a share."
    gap = (
        "The evaluations reviewed here do not establish the share of programmes "
        "with this component."
    )

    def judge(prompt):
        checks = []
        for row in _review_rows(prompt):
            if row["citations"]:
                status = "supported"
                quotes = [
                    {"citation": 1, "quote": "nutrition education in school meals"}
                ]
            else:
                status = "evidence_gap" if row["text"] == gap else "unsupported"
                quotes = []
            checks.append({"id": row["id"], "status": status, "quotes": quotes})
        return {"scope_issues": [], "sentences": checks}

    events, _, llm = await run_research(
        ['{"queries":[]}', finding, mixed + "\n\n" + finding, finding + "\n\n" + gap],
        [[point(1, "The evaluation documented nutrition education in school meals.")]],
        initial_query="Nutrition education in school meals",
        brief_section_prompt="Report evaluation findings and the programme share.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Programme coverage"}], current=0, mode="update"
        ),
        check=judge,
        prose=lambda prompt: (
            [] if gap in prompt else ["State the evidence limit for programme share."]
        ),
    )
    assert next(event["token"] for event in events if event["type"] == "token") == (
        finding + "\n\n" + gap
    )
    assert events[-1]["section_written"] is True
    repair = next(
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if "statements retained by the citation check" in call.args[0][-1].content
    )
    assert finding in repair
    assert mixed not in repair


@pytest.mark.asyncio
@pytest.mark.parametrize("nepal_countries", ["Nepal; India", ["Nepal", "India"]])
@pytest.mark.parametrize(
    "lead",
    ["In Nepal, stakeholders", "The evaluation in Nepal found that stakeholders"],
)
async def test_brief_repairs_country_mismatch_the_semantic_citation_check_missed(
    nepal_countries,
    lead,
):
    cambodia = point(1, "Stakeholders reported that pupils kept washing their hands.")
    cambodia.payload.update(
        map_country="Cambodia", map_title="School meals in Cambodia"
    )
    nepal = point(2, "The evaluation assessed meal delivery to rural schools.")
    nepal.payload.update(map_country=nepal_countries, map_title="School meals in Nepal")
    original = f"{lead} reported that pupils kept washing their hands [1]."
    corrected = original.replace("Nepal", "Cambodia")

    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (original.split(" [1]")[0], 1, "pupils kept washing their hands")
            ),
            _brief_draft(
                (corrected.split(" [1]")[0], 1, "pupils kept washing their hands")
            ),
        ],
        [[cambodia, nepal]],
        initial_query="Handwashing in school meal programmes",
        brief_section_prompt="Describe where sustained handwashing was reported.",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Hygiene outcomes"}], current=0
        ),
    )
    assert (
        next(event["token"] for event in events if event["type"] == "token")
        == corrected
    )
    assert events[-1]["section_written"] is True
    assert any(
        "[1] do not identify nepal as the location" in call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
    )


@pytest.mark.parametrize("source", [None, "other-dataset"])
@pytest.mark.asyncio
async def test_prior_sources_without_matching_dataset_cannot_supply_evidence(source):
    history = [
        {
            "role": "assistant",
            "content": "Former answer [1].",
            "sources": [
                {
                    "index": 1,
                    "dataSource": source,
                    "chunkId": "old-chunk",
                    "title": "Unverified report",
                    "text": "Unverified claim.",
                }
            ],
        }
    ]
    events, _, llm = await run_research(
        [
            '{"query":"local procurement results","reason":"Look up the requested evidence."}',
            '{"queries":[]}',
        ],
        [[]],
        history=history,
        query="What about those procurement results?",
    )
    assert "couldn’t find evidence" in next(
        event["token"] for event in events if event["type"] == "token"
    )
    assert not any(event["type"] == "sources" for event in events)
    assert "Unverified claim." not in llm.ainvoke.await_args.args[0][-1].content


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
    assert "json_invalid" in correction
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
async def test_deep_assistant_retries_an_opening_that_skips_independent_streams():
    streams = [
        {"topic": "Coverage", "query": "Access to services and enrolment"},
        {"topic": "Costs", "query": "Cost per treatment and staffing"},
    ]
    evidence = "Coverage was 60%."
    events, search, llm = await run_research(
        [
            '{"queries":[]}',
            json.dumps({"streams": streams}),
            '{"queries":[]}',
            '{"queries":[]}',
            "## Coverage\n\nCoverage was 60% [1].",
        ],
        [[point(1, evidence)], [point(2, "Families reached service points.")], []],
        deep=True,
    )

    assert search.call_count == 3
    assert "streams" in llm.ainvoke.await_args_list[1].args[0][-1].content
    assert any(event.get("phase") == "checking_citations" for event in events)
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_brief_keeps_sourced_restart_results_for_the_assigned_firmware():
    prior = "Devices with firmware version 2.0 failed to restart"
    current = "Devices with firmware version 2.1 restarted within six seconds"
    unlabelled = "Devices restarted on the second attempt"
    heading = "Restart times with firmware version 2.1"

    def check_scope(prompt, rows):
        assert f'Assigned heading: "{heading}"' in prompt
        assert 'Other headings: ["Earlier versions"]' in prompt
        unrelated_row = next(row for row in rows if unlabelled in row["text"])
        assert unrelated_row["sources"] == [
            {"title": "Report 3", "subject_quote": unlabelled + "."}
        ]
        return [
            {
                "id": row["id"],
                "subject": "device restart",
                "reason": "Match the requested firmware version.",
                "keep": "version 2.1" in row["text"],
            }
            for row in rows
        ]

    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (prior, 1, prior), (current, 2, current), (unlabelled, 3, unlabelled)
            ),
        ],
        [[point(1, prior + "."), point(2, current + "."), point(3, unlabelled + ".")]],
        query=heading,
        brief_section=BriefSectionPrompt(
            outline=[{"title": heading}, {"title": "Earlier versions"}], current=0
        ),
        scope_check=check_scope,
    )

    assert next(e["token"] for e in events if e["type"] == "token") == current + " [1]."


@pytest.mark.asyncio
@pytest.mark.parametrize("exhaust_repair", [False, True])
async def test_brief_selects_direct_evidence_even_when_citation_checking_is_off(
    exhaust_repair,
):
    heading = "Delivery delays for orders placed after the policy change"
    earlier = "Orders placed before the policy change were delayed by five days"
    relevant = "Orders placed after the policy change were delayed by one day"
    remedies = "The team added a second packing station"

    def select(prompt, labels):
        assert (
            heading in prompt
            and earlier in prompt
            and relevant in prompt
            and remedies in prompt
        )
        assert "about 150 words" in prompt
        assert labels == [1, 2]
        if "previous selection" in prompt:
            assert "Passage label 42 is unavailable." in prompt
            assert "Select finding lines from 1 to 2 in [2]." in prompt
            assert "Available labels: [1, 2]" in prompt
            if exhaust_repair:
                return [
                    {
                        "citation": 42,
                        "subject_line": 0,
                        "finding_lines": [1],
                    }
                ]
            return [
                {
                    "citation": 2,
                    "subject_line": 1,
                    "finding_lines": [1],
                }
            ]
        return [
            {
                "citation": 2,
                "subject_line": 1,
                "finding_lines": [1, 17],
            },
            {
                "citation": 42,
                "subject_line": 0,
                "finding_lines": [1],
            },
        ]

    events, _, llm = await run_research(
        ['{"queries":[]}', _brief_draft((relevant, 2, relevant)), ""],
        [[point(1, earlier + "."), point(2, f"{relevant}. {remedies}.")]],
        query=heading,
        brief_section=BriefSectionPrompt(outline=[{"title": heading}], current=0),
        select_evidence=select,
        check_citations=False,
        target_words=150,
    )
    draft_prompt = llm.ainvoke.await_args_list[-1].args[0][-1].content
    assert relevant in draft_prompt and earlier not in draft_prompt
    assert remedies not in draft_prompt
    assert next(event["token"] for event in events if event["type"] == "token") == (
        relevant + " [1]."
    )
    assert not any(event.get("phase") == "checking_citations" for event in events)


@pytest.mark.asyncio
async def test_brief_extraction_accepts_multiple_distinct_observations_from_one_passage():
    observations = [
        "The audit found four missing inventory records",
        "Two stock counts omitted returned items",
        "The year-end count included one sealed pallet",
        "Labels on three shelves were unreadable",
    ]

    def select(_prompt, _labels):
        return [
            {
                "citation": 1,
                "subject_line": 1,
                "finding_lines": [1, 2, 3, 4],
            }
        ]

    events, _, llm = await run_research(
        ['{"queries":[]}', _brief_draft((observations[0], 1, observations[0]))],
        [[point(1, ". ".join(observations) + ".")]],
        query="Inventory audit observations",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Inventory audit observations"}], current=0
        ),
        select_evidence=select,
    )
    draft = next(
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    )
    assert all(observation in draft for observation in observations)
    assert next(event["token"] for event in events if event["type"] == "token") == (
        observations[0] + " [1]."
    )


@pytest.mark.asyncio
async def test_brief_retries_the_supported_part_of_a_finding_reserved_for_two_headings():
    heading = "Restart failures during cold-soak testing"
    finding = "Two control units failed to restart below freezing"
    case = (
        "In the cold-soak test, one control unit stalled before loading its diagnostics"
    )
    response = "The team replaced its power supply"
    mixed = f"{case}, and the team replaced its power supply"
    unrelated = "All tested units failed to restart below freezing"
    limit = "The report does not give the overall failure rate."
    voice = "Use plain language and speak to maintenance leads."

    def review_scope(_prompt, rows):
        return [
            {
                "id": row["id"],
                "subject": "cold-soak testing",
                "reason": "The observation belongs here. Leave replacement to the next section.",
                "keep": response.lower() not in row["text"].lower(),
            }
            for row in rows
        ]

    def verify(prompt):
        return {
            "scope_issues": [],
            "sentences": [
                {
                    "id": row["id"],
                    "status": (
                        "unsupported"
                        if unrelated in row["text"]
                        else "supported" if row["citations"] else "evidence_gap"
                    ),
                    "quotes": [],
                }
                for row in _review_rows(prompt)
            ],
        }

    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                (finding, 1, finding), (mixed, 2, case), (unrelated, 1, finding)
            ),
            _brief_draft((finding, 1, finding), (case, 2, case), limit=limit),
        ],
        [[point(1, finding + "."), point(2, case + ". " + response + ".")]],
        query=heading,
        brief_section=BriefSectionPrompt(
            outline=[{"title": heading}, {"title": "Corrective actions"}],
            current=0,
            voice_instructions=voice,
        ),
        scope_check=review_scope,
        check=verify,
        target_words=150,
    )

    drafts = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert len(drafts) == 2
    assert mixed in drafts[-1] and "Aim for about 150 words" in drafts[-1]
    assert f"Finding removed during evidence check: {unrelated}" in drafts[-1]
    assert all(f'Voice and audience: "{voice}"' in draft for draft in drafts)
    answer = next(event["token"] for event in events if event["type"] == "token")
    assert answer == f"{finding} [1]. {case} [2].\n\n{limit}"


@pytest.mark.asyncio
async def test_brief_scope_reviewer_knows_which_headings_belong_under_an_introduction():
    finding = "The inspection covered how the components age in storage"

    def scope(prompt, rows):
        assert 'Subheadings introduced here: ["Packaging", "Temperature"]' in prompt
        assert 'Other headings: ["Packaging", "Temperature", "Delivery"]' in prompt
        return [
            {
                "id": rows[0]["id"],
                "subject": "Storage",
                "reason": "Frames both topics.",
                "keep": True,
            }
        ]

    events, _, llm = await run_research(
        ['{"queries":[]}', _brief_draft((finding, 1, finding))],
        [[point(1, finding + ".")]],
        brief_section=BriefSectionPrompt(
            outline=[
                {"title": "Storage"},
                {"title": "Packaging", "level": 2},
                {"title": "Temperature", "level": 2},
                {"title": "Delivery"},
            ],
            current=0,
        ),
        scope_check=scope,
    )
    draft = next(
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    )
    assert 'This section opens these subheadings: ["Packaging", "Temperature"]' in draft
    assert next(e["token"] for e in events if e["type"] == "token") == f"{finding} [1]."


@pytest.mark.asyncio
async def test_brief_checks_a_scope_revision_against_its_original_citation():
    observation = "One pump lost pressure during the overnight test"
    action = "The team replaced the inlet valve"
    mixed = f"{observation}, and the team replaced the inlet valve"
    heading = "Pressure problems during the test"
    voice = "Use plain English and attribution."

    def scope(prompt, rows):
        assert voice in prompt
        assert len(rows) == 1 and mixed in rows[0]["text"]
        return [
            {
                "id": rows[0]["id"],
                "subject": heading,
                "reason": "Valve replacement belongs in the corrective actions section.",
                "keep": True,
                "covers_other_heading": True,
                "in_scope_revision": observation,
            }
        ]

    def verify(prompt):
        row = _review_rows(prompt)[0]
        assert row["text"] == observation + " [1]."
        assert observation in row["prepared_quotes"][0]["quote"]
        return {
            "scope_issues": [],
            "sentences": [{"id": row["id"], "status": "supported", "quotes": []}],
        }

    events, _, _ = await run_research(
        ['{"queries":[]}', _brief_draft((mixed, 1, observation))],
        [[point(1, f"{observation}. {action}.")]],
        query=heading,
        brief_section=BriefSectionPrompt(
            outline=[{"title": heading}, {"title": "Corrective actions"}],
            current=0,
            voice_instructions=voice,
        ),
        scope_check=scope,
        check=verify,
    )
    assert next(event["token"] for event in events if event["type"] == "token") == (
        observation + " [1]."
    )


@pytest.mark.asyncio
async def test_brief_removes_a_repeated_finding_without_dropping_a_distinct_measurement():
    quote = "Two pumps lost pressure overnight and three lost pressure at midday"
    first = "Two pumps lost pressure during the overnight test"
    repeated = "During the overnight test, two pumps lost pressure"
    distinct = "Three pumps lost pressure during the midday test"

    def duplicate(rows):
        assert [row["text"] for row in rows] == [
            f"{finding} [1]." for finding in (first, repeated, distinct)
        ]
        return [
            {
                "id": rows[1]["id"],
                "pairs": [{"new_clause": repeated, "existing_clause": first}],
            }
        ]

    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft((first, 1, quote), (repeated, 1, quote), (distinct, 1, quote)),
        ],
        [[point(1, quote + ".")]],
        query="Pressure test results",
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Pressure test results"}], current=0
        ),
        find_duplicates=duplicate,
    )
    assert next(event["token"] for event in events if event["type"] == "token") == (
        f"{first} [1]. {distinct} [1]."
    )


@pytest.mark.asyncio
async def test_brief_replans_a_duplicate_query_when_the_exact_population_is_still_missing():
    first = "Language barriers for children returning to school in Albania"
    alternate = (
        "Albanian language proficiency of returnee pupils in the Western Balkans"
    )
    finding = "Returnee pupils who lived abroad struggled with Albanian"
    events, search, llm = await run_research(
        [
            json.dumps(
                {"queries": [first], "reason": "The documents omit returnee pupils."}
            ),
            json.dumps(
                {
                    "queries": [alternate],
                    "reason": "Find reports that cover returnee pupils.",
                }
            ),
            '{"queries":[]}',
            _brief_draft((finding, 2, finding)),
        ],
        [
            [point(1, "The first report covered another population.")],
            [point(2, finding + ".")],
        ],
        query=first,
        deep=True,
        brief_section=BriefSectionPrompt(outline=[{"title": first}], current=0),
    )

    request = llm.ainvoke.await_args_list[1].args[0][-1].content
    assert "The documents omit returnee pupils." in request and first in request
    assert [call.kwargs["query"] for call in search.call_args_list] == [
        first,
        alternate,
    ]
    assert events[-1]["section_written"] is True


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
@pytest.mark.parametrize(
    ("geographic_scope", "planner_scope"),
    [("", ""), ("Cambodia", "Cambodia"), ("", "Kenya and Cambodia")],
)
@pytest.mark.asyncio
async def test_broad_question_researches_each_stream_from_its_own_results_and_joins(
    deep, per_stream, geographic_scope, planner_scope
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
                    "geographic_scope": planner_scope,
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
        [[point(1, "The evidence was documented.")]],
    )
    assert search.call_count == 1
    assert events[-1]["type"] == "done"
    assert (
        "previous reply did not match"
        in llm.ainvoke.await_args_list[1].args[0][-1].content
    )


@pytest.mark.asyncio
async def test_short_section_checks_unused_search_hits_for_additional_supported_findings():
    first = "The initial audit recorded a week of delay"
    later = "The later audit traced the delay to an approval queue"
    rows = [point(1, first + ".")]
    rows.extend(point(i, "A different topic.") for i in range(2, 13))
    rows.append(point(13, later + "."))
    events, search, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft((first, 1, first)),
            _brief_draft((first, 1, first)),
            _brief_draft((first, 1, first), (later, 13, later)),
            _brief_draft((first, 1, first), (later, 13, later)),
        ],
        [rows],
        target_words=100,
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Processing delays"}], current=0
        ),
    )
    assert search.call_count == 1
    answer = next(e["token"] for e in events if e["type"] == "token")
    assert first in answer and later in answer
    assert {
        s["chunkId"] for e in events if e["type"] == "sources" for s in e["sources"]
    } == {"chunk-1", "chunk-13"}


@pytest.mark.asyncio
async def test_brief_revision_only_uses_notes_with_sources_in_the_new_selection():
    old = "The first audit recorded 29 interruptions"
    new = "The second audit identified a sticking valve in the backup pump"
    passages = [point(1, old + ".")]
    passages.extend(point(i, "An unrelated inspection.") for i in range(2, 13))
    passages.append(point(13, new + "."))

    def select(prompt, labels):
        if 13 in labels:
            assert "Previous draft:" in prompt and old + " [1]." in prompt
        label = 13 if 13 in labels else 1
        return [{"citation": label, "subject_line": 1, "finding_lines": [1]}]

    events, _, llm = await run_research(
        [
            '{"queries":[]}',
            _brief_draft((old, 1, old)),
            _brief_draft((old, 1, old)),
            _brief_draft((new, 13, new)),
            _brief_draft((new, 13, new)),
        ],
        [passages],
        target_words=100,
        select_evidence=select,
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Pump reliability"}], current=0
        ),
    )
    drafts = [
        call.args[0][-1].content
        for call in llm.ainvoke.await_args_list
        if call.args[0][0].content.startswith("Write the prose of one section")
    ]
    assert len(drafts) == 4
    assert old in drafts[1]
    assert all(old not in draft and new in draft for draft in drafts[2:])
    assert next(e["token"] for e in events if e["type"] == "token") == f"{new} [1]."


@pytest.mark.asyncio
async def test_brief_rejects_unsupported_frequency_and_a_source_for_the_wrong_subject():
    quote = "Some components needed replacement"
    wrong = "Certified components had to be replaced"
    revised = "The inspection found some components needed replacement"

    def scope(_prompt, rows):
        return [
            {
                "id": r["id"],
                "subject": "components",
                "reason": "The source documents occurrence.",
                "source_matches_assignment": r["id"] == 1,
                "unsupported_phrases": ["usually"],
                "keep": True,
                "in_scope_revision": revised,
            }
            for r in rows
        ]

    events, _, _ = await run_research(
        [
            '{"queries":[]}',
            _brief_draft(
                ("Components usually needed replacement", 1, quote), (wrong, 2, wrong)
            ),
        ],
        [[point(1, quote + "."), point(2, wrong + ".")]],
        brief_section=BriefSectionPrompt(
            outline=[{"title": "Inspections of new components"}], current=0
        ),
        scope_check=scope,
    )
    answer = next(e["token"] for e in events if e["type"] == "token")
    assert answer == revised + " [1]."
