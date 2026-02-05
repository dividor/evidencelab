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
async def test_generate_ai_summary_cleans_prefixes(monkeypatch):
    class FakeLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content='"User: Hello\nAssistant: World"')

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
        async def astream(self, _messages):
            for token in ["Hello ", "world"]:
                yield SimpleNamespace(content=token)

    monkeypatch.setattr(
        llm_service,
        "get_llm",
        lambda model=None, temperature=None, max_tokens=None: FakeLLM(),
    )

    chunks = []
    async for token in llm_service.stream_ai_summary("query", [{"text": "a"}]):
        chunks.append(token)

    assert "".join(chunks) == "Hello world"


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
