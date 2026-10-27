"""Summary modes, prompts and progress in the shared summarising core."""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from pipeline.processors.summarization.summarizer import SummarizeProcessor
from pipeline.processors.summarization.summary_text import (
    DEFAULT_SINGLE_PROMPT_CONTEXT_WINDOW,
    MODE_MAP_REDUCE,
    MODE_SINGLE_PROMPT,
    SUMMARY_USER_SET_FIELD,
    SummaryTextMixin,
    SummaryTooLargeError,
    TokenCountUnavailableError,
    count_prompt_tokens,
    default_summary_instructions,
    render_map_prompt,
    render_reduce_prompt,
    resolve_summary_mode,
)

pytestmark = pytest.mark.unit

SUMMARY = "## Summary\n\n" + "A faithful summary of the source text. " * 3
CUSTOM_PROMPT = "Write three bullet points on the main findings. Use 'plain' words."


class FakeSummarizer(SummaryTextMixin):
    """A host for the mixin whose LLM records its prompts."""

    def __init__(
        self,
        mode: str = MODE_MAP_REDUCE,
        context_window: int = 3000,
        single_window: Optional[int] = None,
        instructions: str = "",
    ) -> None:
        self.config = {"chunk_overlap": 0}
        self.context_window = context_window
        self.max_tokens = 100
        self.workers = 1
        self.model_key = "model-key"
        self.model_name = "model-name"
        self.summary_mode = mode
        self.single_prompt_context_window = single_window
        self.summary_instructions = instructions
        self.events: List[Dict[str, Any]] = []
        self._progress = self.events.append
        self.calls: List[Tuple[str, str, bool]] = []
        self.counted: List[str] = []

    def _invoke_llm(self, prompt: str, model: str, include_inference: bool) -> str:
        self.calls.append((prompt, model, include_inference))
        return SUMMARY

    def _count_prompt_tokens(self, prompt: str) -> int:
        # Four characters a token, like English text with most tokenizers.
        self.counted.append(prompt)
        return len(prompt) // 4


def _prompt_tokens(text: str) -> int:
    return len(render_map_prompt(text, default_summary_instructions())) // 4


class TestModeAndPrompts:
    def test_mode_defaults_to_map_reduce(self):
        assert resolve_summary_mode({}) == MODE_MAP_REDUCE
        assert resolve_summary_mode({"mode": "single_prompt"}) == MODE_SINGLE_PROMPT

    def test_unknown_mode_is_an_error_naming_the_key(self):
        with pytest.raises(ValueError, match="summarize.mode"):
            resolve_summary_mode({"mode": "one_shot"})

    def test_default_prompt_is_the_output_format_instructions(self):
        prompt = default_summary_instructions()
        assert prompt.startswith("OUTPUT FORMAT")
        assert "## Summary" in prompt

    def test_prompts_wrap_the_text_and_keep_the_instructions_unescaped(self):
        map_prompt = render_map_prompt("Body & <text>", CUSTOM_PROMPT)
        assert "<<< Body &amp; &lt;text&gt; >>>" in map_prompt
        assert map_prompt.endswith(CUSTOM_PROMPT)
        reduce_prompt = render_reduce_prompt("Part summaries", CUSTOM_PROMPT)
        assert "<<< Part summaries >>>" in reduce_prompt
        assert reduce_prompt.endswith(CUSTOM_PROMPT)


class TestSinglePrompt:
    def test_sends_all_the_text_in_one_call(self):
        text = "Finding. " * 2000  # far larger than the map-reduce window
        summarizer = FakeSummarizer(MODE_SINGLE_PROMPT, single_window=50000)

        summary, _ = summarizer._llm_summary(text)

        assert summary == SUMMARY
        assert len(summarizer.calls) == 1
        prompt, model, include_inference = summarizer.calls[0]
        assert text.strip()[:200] in prompt
        assert summarizer.counted == [prompt]  # the exact prompt is counted
        assert (model, include_inference) == ("model-key", True)
        assert summarizer.events == [{"stage": "single"}]

    def test_a_prompt_over_the_limit_is_an_error_with_both_sizes(self):
        text = "x" * 40000
        tokens = _prompt_tokens(text)
        window = tokens + 100 - 1  # one token short, counting the 100 kept for output
        summarizer = FakeSummarizer(MODE_SINGLE_PROMPT, single_window=window)

        with pytest.raises(SummaryTooLargeError) as err:
            summarizer._llm_summary(text)

        assert f"The prompt is {tokens:,} tokens" in str(err.value)
        assert f"more than the {window:,} tokens" in str(err.value)
        assert summarizer.calls == []

    def test_a_prompt_exactly_at_the_limit_is_sent(self):
        text = "x" * 40000
        summarizer = FakeSummarizer(
            MODE_SINGLE_PROMPT, single_window=_prompt_tokens(text) + 100
        )
        summarizer._llm_summary(text)
        assert len(summarizer.calls) == 1

    def test_the_limit_defaults_to_gemini_2_5_flash_input_tokens(self):
        assert DEFAULT_SINGLE_PROMPT_CONTEXT_WINDOW == 1_048_576
        # About 1.6M characters: refused by a one-character-per-token rule,
        # but about 400k tokens, so within the default window.
        text = "Findings and evidence. " * 70000
        summarizer = FakeSummarizer(MODE_SINGLE_PROMPT, single_window=None)
        summarizer._llm_summary(text)
        assert len(summarizer.calls) == 1

        too_big = "y" * (4 * DEFAULT_SINGLE_PROMPT_CONTEXT_WINDOW)
        with pytest.raises(SummaryTooLargeError, match="1,048,576 tokens"):
            FakeSummarizer(MODE_SINGLE_PROMPT)._llm_summary(too_big)


class CountingModel:
    """A chat model with its own token counting."""

    def get_num_tokens(self, text: str) -> int:
        return len(text.split())


class TestTokenCounting:
    def test_counts_with_the_models_own_tokenizer(self):
        assert count_prompt_tokens(CountingModel(), "three short words") == 3

    def test_a_model_without_exact_counting_is_refused(self):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        with pytest.raises(TokenCountUnavailableError, match="FakeListChatModel"):
            count_prompt_tokens(FakeListChatModel(responses=["x"]), "text")


class TestMapReduce:
    def test_small_text_is_one_call(self):
        summarizer = FakeSummarizer(MODE_MAP_REDUCE, context_window=8000)
        summarizer._llm_summary("A short document. " * 10)
        assert len(summarizer.calls) == 1
        assert summarizer.events == [{"stage": "single"}]

    def test_large_text_maps_each_part_then_combines_them(self):
        summarizer = FakeSummarizer(MODE_MAP_REDUCE, context_window=8000)
        window = summarizer._effective_max_chars(8000 - 100)
        text = "y" * (window * 2 + 10)  # three parts

        summarizer._llm_summary(text)

        assert len(summarizer.calls) == 4
        assert [c[1] for c in summarizer.calls] == ["model-name"] * 4
        assert summarizer.events == [
            {"stage": "map", "done": 1, "total": 3},
            {"stage": "map", "done": 2, "total": 3},
            {"stage": "map", "done": 3, "total": 3},
            {"stage": "reduce", "depth": 0},
        ]
        assert "Here are the interim summaries" in summarizer.calls[-1][0]

    def test_a_custom_prompt_is_used_in_every_step(self):
        summarizer = FakeSummarizer(
            MODE_MAP_REDUCE, context_window=8000, instructions=CUSTOM_PROMPT
        )
        window = summarizer._effective_max_chars(8000 - 100)
        summarizer._llm_summary("z" * (window + 10))
        assert len(summarizer.calls) == 3
        assert all(prompt.endswith(CUSTOM_PROMPT) for prompt, _, _ in summarizer.calls)
        assert all("OUTPUT FORMAT" not in prompt for prompt, _, _ in summarizer.calls)


class TestPipelineProcessor:
    @staticmethod
    def _processor(**extra: Any) -> SummarizeProcessor:
        processor = SummarizeProcessor(
            {"llm_model": {"model": "gpt-3.5-turbo"}, "context_window": 29000, **extra}
        )
        processor._initialized = True
        return processor

    def test_counts_the_prompt_with_its_own_model(self, monkeypatch):
        processor = self._processor()
        built = []

        def build(model, include_inference):
            built.append((model, include_inference))
            return CountingModel()

        monkeypatch.setattr(processor, "_build_llm", build)
        assert processor._count_prompt_tokens("one two three four") == 4
        assert built == [("gpt-3.5-turbo", True)]

    def test_reads_the_mode_and_window_from_config(self):
        processor = self._processor(
            mode="single_prompt", single_prompt_context_window=120000
        )
        assert processor.summary_mode == MODE_SINGLE_PROMPT
        assert processor.single_prompt_context_window == 120000
        assert processor.summary_instructions == default_summary_instructions()

    def test_unknown_mode_stops_the_processor(self):
        with pytest.raises(ValueError, match="summarize.mode"):
            self._processor(mode="fastest")

    def test_keeps_a_summary_set_in_the_app(self, monkeypatch):
        processor = self._processor()
        monkeypatch.setattr(
            processor, "_invoke_llm", lambda *a: pytest.fail("LLM must not be called")
        )
        doc = {
            "id": "doc-1",
            "map_title": "Report",
            "sys_parsed_folder": "/nonexistent",
            "sys_full_summary": "Edited by an administrator.",
            "sys_data": {
                SUMMARY_USER_SET_FIELD: True,
                "sys_summarization_method": "ui_edited",
            },
        }

        result = processor.process_document(doc)

        assert result["success"] is True
        assert result["updates"]["sys_full_summary"] == "Edited by an administrator."
        assert result["updates"]["sys_summarization_method"] == "ui_edited"

    def test_summarises_again_once_the_mark_is_cleared(self):
        processor = self._processor()
        doc = {
            "id": "doc-1",
            "map_title": "Report",
            "sys_parsed_folder": "/nonexistent",
            "sys_full_summary": "Edited by an administrator.",
            "sys_data": {SUMMARY_USER_SET_FIELD: False},
        }
        result = processor.process_document(doc)
        # It goes on to summarise, and fails only because there is no parsed folder.
        assert result["success"] is False
        assert result["updates"]["sys_error_message"] == "Parsed folder not found"
