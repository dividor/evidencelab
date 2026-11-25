from types import SimpleNamespace

import pytest

import ui.backend.services.llm_service as llm_service


def test_render_prompt_includes_query_and_results():
    prompt = llm_service.render_prompt(
        query="energy access",
        results=[
            {
                "title": "Energy Report",
                "organization": "UN",
                "year": 2024,
                "text": "Highlights on access.",
            }
        ],
    )

    assert "SYSTEM MESSAGE:" in prompt
    assert "USER MESSAGE:" in prompt
    assert "energy access" in prompt
    assert "Energy Report" in prompt


@pytest.mark.asyncio
async def test_generate_ai_summary_returns_stripped_content(monkeypatch):
    class FakeLLM:
        # Accept a ``config`` kwarg so the UsageMetadataCallbackHandler
        # added in the token-usage feature can be threaded through.
        async def ainvoke(self, _messages, config=None):
            return SimpleNamespace(content="  Hello World  ")

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeLLM(),
    )

    summary = await llm_service.generate_ai_summary("query", [{"text": "a"}])

    assert summary == "Hello World"


@pytest.mark.asyncio
async def test_generate_ai_summary_raises_on_error(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: (_ for _ in ()).throw(
            RuntimeError("fail")
        ),
    )
    with pytest.raises(RuntimeError, match="fail"):
        await llm_service.generate_ai_summary("query", [{"text": "a"}, {"text": "b"}])


@pytest.mark.asyncio
async def test_stream_ai_summary_yields_tokens(monkeypatch):
    class FakeLLM:
        async def astream(self, _messages, config=None):
            for token in ["Hello ", "world"]:
                yield SimpleNamespace(content=token)

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeLLM(),
    )

    chunks = []
    async for token in llm_service.stream_ai_summary("query", [{"text": "a"}]):
        if isinstance(token, str):
            chunks.append(token)

    assert "".join(chunks) == "Hello world"


@pytest.mark.asyncio
async def test_stream_ai_summary_when_chunks_are_content_blocks_then_yields_text(
    monkeypatch,
):
    """Bedrock streams content as lists of blocks; users saw the raw lists."""
    from langchain_core.messages import AIMessageChunk

    class FakeBedrockLLM:
        async def astream(self, _messages, config=None):
            yield AIMessageChunk(
                content=[{"type": "text", "text": "The most", "index": 0}]
            )
            yield AIMessageChunk(content=[])
            yield AIMessageChunk(
                content=[{"type": "text", "text": " common", "index": 0}]
            )

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeBedrockLLM(),
    )

    chunks = [
        token
        async for token in llm_service.stream_ai_summary("query", [{"text": "a"}])
        if isinstance(token, str)
    ]

    assert chunks == ["The most", " common"]


@pytest.mark.asyncio
async def test_stream_ai_summary_raises_on_error(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: (_ for _ in ()).throw(
            RuntimeError("fail")
        ),
    )
    with pytest.raises(RuntimeError, match="fail"):
        async for _ in llm_service.stream_ai_summary("query", [{"text": "a"}]):
            pass


# A passage as the pipeline stores it: a heading breadcrumb, the report's own
# paragraph number, a footnote marker and a bracketed reference to the report's
# bibliography. Models cited these numbers as if they were result numbers.
_NUMBERED_PASSAGE = (
    "-- Findings --  118. Coverage reached 54 percent of children.[^5] "
    "In Chad, flooding cut access to sites [12]."
)


def _numbered_results():
    return [
        {
            "title": "Chad evaluation",
            "organization": "WFP",
            "year": 2023,
            "text": _NUMBERED_PASSAGE,
        },
        {
            "title": "Mali evaluation",
            "organization": "WFP",
            "year": 2022,
            "text": "45. Recovery rates rose.",
        },
    ]


def _assert_report_numbers_removed(prompt):
    assert (
        "Full Text: -- Findings --  Coverage reached 54 percent of children. "
        "In Chad, flooding cut access to sites." in prompt
    )
    assert "Full Text: Recovery rates rose." in prompt
    for report_number in ("118.", "[^5]", "[12]", "45."):
        assert report_number not in prompt


def test_render_prompt_when_passages_carry_report_numbers_then_prompt_omits_them():
    prompt = llm_service.render_prompt(query="coverage", results=_numbered_results())

    _assert_report_numbers_removed(prompt)
    # The numbers the model should cite are still there.
    assert "[1] Chad evaluation (WFP, 2023)" in prompt
    assert "[2] Mali evaluation (WFP, 2022)" in prompt


def test_render_prompt_when_passages_are_cleaned_then_callers_results_are_unchanged():
    results = _numbered_results()

    llm_service.render_prompt(query="coverage", results=results)

    assert results == _numbered_results()


def test_render_prompt_when_more_results_than_max_then_sends_only_the_top_ones():
    prompt = llm_service.render_prompt(
        query="coverage", results=_numbered_results(), max_results=1
    )

    assert "Chad evaluation" in prompt
    assert "Mali evaluation" not in prompt


@pytest.mark.asyncio
async def test_stream_ai_summary_when_passages_numbered_then_model_reads_clean_text(
    monkeypatch,
):
    sent = []

    class FakeLLM:
        async def astream(self, messages, config=None):
            sent.extend(messages)
            yield SimpleNamespace(content="ok")

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeLLM(),
    )
    results = _numbered_results()

    async for _ in llm_service.stream_ai_summary("coverage", results):
        pass

    _assert_report_numbers_removed(sent[-1].content)
    assert results == _numbered_results()


@pytest.mark.asyncio
async def test_generate_ai_summary_with_usage_when_passages_numbered_then_model_reads_clean_text(
    monkeypatch,
):
    sent = []

    class FakeLLM:
        async def ainvoke(self, messages, config=None):
            sent.extend(messages)
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeLLM(),
    )
    results = _numbered_results()

    summary, _usage = await llm_service.generate_ai_summary_with_usage(
        "coverage", results
    )

    assert summary == "ok"
    _assert_report_numbers_removed(sent[-1].content)
    assert results == _numbered_results()
