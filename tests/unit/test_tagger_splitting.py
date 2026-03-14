"""
Unit tests for TOC payload splitting in tagger_llm.py.

Tests cover:
- _split_toc_entries: batching TOC entries when payload exceeds budget
- call_llm_for_toc: full-prompt char comparison triggers splitting
"""

import json
from unittest.mock import MagicMock, patch

from pipeline.processors.tagging.tagger_llm import (
    _CHARS_PER_TOKEN,
    _split_toc_entries,
    build_toc_items_payload,
    build_toc_prompts,
    call_llm_for_toc,
    validate_llm_output,
)


def _make_toc_entries(n: int) -> list:
    """Create n synthetic TOC entries."""
    return [
        {"index": i, "title": f"Section {i}: {'A' * 40}", "level": 2, "page": i + 1}
        for i in range(n)
    ]


class TestSplitTocEntries:
    """Test _split_toc_entries batching logic."""

    def test_single_batch_when_under_limit(self):
        """All entries fit in one batch when payload is small."""
        entries = _make_toc_entries(5)
        locked = {}
        payload = build_toc_items_payload(entries, locked)
        budget = len(json.dumps(payload, ensure_ascii=False)) + 100
        batches = _split_toc_entries(entries, locked, budget)
        assert len(batches) == 1
        assert batches[0] == entries

    def test_splits_when_over_limit(self):
        """Entries are split into multiple batches when payload exceeds budget."""
        entries = _make_toc_entries(20)
        locked = {}
        payload = build_toc_items_payload(entries, locked)
        full_chars = len(json.dumps(payload, ensure_ascii=False))
        # Set budget to half the full payload size to force a split
        budget = full_chars // 2
        batches = _split_toc_entries(entries, locked, budget)
        assert len(batches) >= 2
        # All entries are preserved across batches
        all_entries = []
        for batch in batches:
            all_entries.extend(batch)
        assert len(all_entries) == len(entries)

    def test_preserves_entry_order(self):
        """Entries maintain their original order across batches."""
        entries = _make_toc_entries(10)
        locked = {}
        batches = _split_toc_entries(entries, locked, max_payload_chars=100)
        all_indices = []
        for batch in batches:
            all_indices.extend(e["index"] for e in batch)
        assert all_indices == list(range(10))

    def test_locked_labels_preserved_in_payload(self):
        """Locked labels appear in the payload for their respective entries."""
        entries = _make_toc_entries(5)
        locked = {0: "introduction", 3: "conclusions"}
        payload = build_toc_items_payload(entries, locked)
        assert payload[0]["locked_label"] == "introduction"
        assert payload[3]["locked_label"] == "conclusions"
        assert payload[1]["locked_label"] is None

    def test_very_small_budget_still_produces_batches(self):
        """Even with a tiny budget, every entry ends up in a batch."""
        entries = _make_toc_entries(10)
        locked = {}
        batches = _split_toc_entries(entries, locked, max_payload_chars=1)
        total = sum(len(b) for b in batches)
        assert total == 10

    def test_empty_entries_returns_single_empty_batch(self):
        """No entries produces a single batch with no entries."""
        batches = _split_toc_entries([], {}, max_payload_chars=1000)
        assert len(batches) == 1
        assert batches[0] == []


class TestCallLlmForTocSplitting:
    """Test that call_llm_for_toc triggers splitting based on full prompt size."""

    @patch("pipeline.processors.tagging.tagger_llm.get_llm")
    @patch("pipeline.processors.tagging.tagger_llm.invoke_and_parse_toc")
    def test_no_split_when_prompt_fits(self, mock_invoke, mock_get_llm):
        """Small TOC doesn't trigger splitting."""
        entries = _make_toc_entries(3)
        locked = {}
        # Mock LLM returns labels for all entries
        mock_invoke.return_value = {i: "introduction" for i in range(3)}
        mock_get_llm.return_value = MagicMock()

        llm_config = {
            "llm_model": {
                "model": "test-model",
                "max_tokens": 4000,
            },
            "context_window": 32000,
        }

        with patch(
            "pipeline.processors.tagging.tagger_llm.SUPPORTED_LLMS",
            {"test-model": {"provider": "huggingface"}},
        ):
            result = call_llm_for_toc(
                document_title="Test Doc",
                toc_entries=entries,
                locked_labels_by_index=locked,
                llm_config=llm_config,
                total_pages=10,
                retry_on_failure=False,
            )

        # invoke_and_parse_toc should be called exactly once (no splitting)
        assert mock_invoke.call_count == 1
        assert len(result) == 3

    @patch("pipeline.processors.tagging.tagger_llm.get_llm")
    @patch("pipeline.processors.tagging.tagger_llm.invoke_and_parse_toc")
    def test_splits_when_prompt_exceeds_window(self, mock_invoke, mock_get_llm):
        """Large TOC triggers splitting into multiple batches."""
        # Create a large TOC that will exceed a small context window
        entries = _make_toc_entries(50)
        locked = {}

        # Return labels for whichever batch entries are passed
        def side_effect(llm, system_prompt, user_prompt, toc_entries, **kwargs):
            return {e["index"]: "introduction" for e in toc_entries}

        mock_invoke.side_effect = side_effect
        mock_get_llm.return_value = MagicMock()

        # Very small context window to force splitting
        llm_config = {
            "llm_model": {
                "model": "test-model",
                "max_tokens": 2000,
            },
            "context_window": 4000,  # Very small to force splitting
        }

        with patch(
            "pipeline.processors.tagging.tagger_llm.SUPPORTED_LLMS",
            {"test-model": {"provider": "huggingface"}},
        ):
            result = call_llm_for_toc(
                document_title="Test Doc",
                toc_entries=entries,
                locked_labels_by_index=locked,
                llm_config=llm_config,
                total_pages=100,
                retry_on_failure=False,
            )

        # Should have been called multiple times (once per batch)
        assert mock_invoke.call_count > 1
        # All entries should have labels
        assert len(result) == 50

    @patch("pipeline.processors.tagging.tagger_llm.get_llm")
    @patch("pipeline.processors.tagging.tagger_llm.invoke_and_parse_toc")
    def test_merged_labels_from_all_batches(self, mock_invoke, mock_get_llm):
        """Labels from different batches are merged into a single result."""
        entries = _make_toc_entries(20)
        locked = {}

        call_count = [0]

        def side_effect(llm, system_prompt, user_prompt, toc_entries, **kwargs):
            call_count[0] += 1
            # Alternate labels to verify merging
            label = "introduction" if call_count[0] % 2 else "conclusions"
            return {e["index"]: label for e in toc_entries}

        mock_invoke.side_effect = side_effect
        mock_get_llm.return_value = MagicMock()

        llm_config = {
            "llm_model": {
                "model": "test-model",
                "max_tokens": 2000,
            },
            "context_window": 4000,
        }

        with patch(
            "pipeline.processors.tagging.tagger_llm.SUPPORTED_LLMS",
            {"test-model": {"provider": "huggingface"}},
        ):
            result = call_llm_for_toc(
                document_title="Test Doc",
                toc_entries=entries,
                locked_labels_by_index=locked,
                llm_config=llm_config,
                total_pages=50,
                retry_on_failure=False,
            )

        # All 20 entries should be labeled
        assert len(result) == 20
        # Labels should come from different batches
        assert "introduction" in result.values()

    @patch("pipeline.processors.tagging.tagger_llm.get_llm")
    @patch("pipeline.processors.tagging.tagger_llm.invoke_and_parse_toc")
    def test_full_prompt_char_comparison(self, mock_invoke, mock_get_llm):
        """Splitting decision is based on full prompt chars, not just payload."""
        entries = _make_toc_entries(10)
        locked = {}

        # Compute what the full prompt would be
        payload = build_toc_items_payload(entries, locked)
        sys_prompt, usr_prompt = build_toc_prompts(
            document_title="Test Doc",
            toc_items_payload=payload,
            total_pages=20,
        )
        full_prompt_chars = len(sys_prompt) + len(usr_prompt)

        # Set context window so available chars is LESS than full prompt chars
        # available_input = context_window - max_tokens
        # max_total_chars = available_input * _CHARS_PER_TOKEN
        # We want max_total_chars < full_prompt_chars
        max_tokens = 2000
        needed_available = full_prompt_chars / _CHARS_PER_TOKEN
        # Set context_window so available_input < needed_available
        context_window = int(needed_available * 0.8) + max_tokens

        mock_invoke.side_effect = lambda *a, **kw: {
            e["index"]: "introduction"
            for e in kw.get("toc_entries", a[3] if len(a) > 3 else [])
        }
        mock_get_llm.return_value = MagicMock()

        llm_config = {
            "llm_model": {
                "model": "test-model",
                "max_tokens": max_tokens,
            },
            "context_window": context_window,
        }

        with patch(
            "pipeline.processors.tagging.tagger_llm.SUPPORTED_LLMS",
            {"test-model": {"provider": "huggingface"}},
        ):
            result = call_llm_for_toc(
                document_title="Test Doc",
                toc_entries=entries,
                locked_labels_by_index=locked,
                llm_config=llm_config,
                total_pages=20,
                retry_on_failure=False,
            )

        # Should have split (multiple invocations)
        assert mock_invoke.call_count > 1
        assert len(result) == 10


class TestValidateLlmOutputBatchIndices:
    """Test validate_llm_output works correctly with batch subsets."""

    def test_validates_high_indices_from_second_batch(self):
        """Entries with high original indices (e.g. batch 2) must pass validation.

        Regression test: previously validate_llm_output used len(toc_entries)
        as the upper bound, which rejected indices >= batch size even though
        those were valid original indices.
        """
        # Simulate batch 2: entries with indices 25-49
        batch_entries = _make_toc_entries(50)[25:]
        assert batch_entries[0]["index"] == 25
        assert batch_entries[-1]["index"] == 49

        # LLM returns labels matching the batch indices
        llm_output = [
            {"idx": e["index"], "label": "introduction"} for e in batch_entries
        ]

        result = validate_llm_output(
            batch_entries, llm_output, locked_labels_by_index={}
        )
        assert result is not None
        assert len(result) == 25
        assert 25 in result
        assert 49 in result

    def test_rejects_index_not_in_batch(self):
        """An index not present in the batch entries should be rejected."""
        batch_entries = _make_toc_entries(50)[25:30]  # indices 25-29
        llm_output = [{"idx": 999, "label": "introduction"}]

        result = validate_llm_output(
            batch_entries, llm_output, locked_labels_by_index={}
        )
        assert result == {}

    def test_sequential_indices_still_work(self):
        """Normal case: indices 0..N-1 in a non-split batch still validate."""
        entries = _make_toc_entries(10)
        llm_output = [{"idx": i, "label": "introduction"} for i in range(10)]

        result = validate_llm_output(entries, llm_output, locked_labels_by_index={})
        assert result is not None
        assert len(result) == 10
