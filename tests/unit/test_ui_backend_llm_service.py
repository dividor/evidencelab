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
