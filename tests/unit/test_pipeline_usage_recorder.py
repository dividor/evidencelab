"""Tests for pipeline LLM usage collection and recording
(``pipeline.utilities.usage_recorder``)."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pipeline.utilities.usage_recorder import UsageCollector, record_pipeline_usage
from ui.backend.utils.llm_footprint import FOOTPRINT_ROW_COLUMNS, estimate_footprint

pytestmark = pytest.mark.unit


def _response(input_tokens=0, output_tokens=0):
    return SimpleNamespace(
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens}
    )


# ---------------------------------------------------------------------------
# UsageCollector
# ---------------------------------------------------------------------------


class TestUsageCollector:
    def test_add_response_accumulates_per_model(self):
        collector = UsageCollector()
        collector.add_response(_response(100, 20), "gpt-4.1-mini")
        collector.add_response(_response(50, 10), "gpt-4.1-mini")
        collector.add_response(_response(7, 3), "gemini-2.0-flash")
        entries = {e["llm_model"]: e for e in collector.entries()}
        gpt = entries["gpt-4.1-mini"]
        assert (gpt["prompt_tokens"], gpt["completion_tokens"], gpt["calls"]) == (
            150,
            30,
            2,
        )
        assert entries["gemini-2.0-flash"]["calls"] == 1

    def test_add_response_when_no_usage_metadata_then_ignored(self):
        collector = UsageCollector()
        collector.add_response(SimpleNamespace(content="hi"), "gpt-4.1-mini")
        collector.add_response(_response(0, 0), "gpt-4.1-mini")
        assert collector.entries() == []

    def test_add_response_without_model_key_uses_unknown(self):
        collector = UsageCollector()
        collector.add_response(_response(5, 5), None)
        assert collector.entries()[0]["llm_model"] == "unknown"

    def test_reset_drops_accumulated_usage(self):
        collector = UsageCollector()
        collector.add_response(_response(5, 5), "m")
        collector.reset()
        assert collector.entries() == []


# ---------------------------------------------------------------------------
# record_pipeline_usage
# ---------------------------------------------------------------------------


class TestRecordPipelineUsage:
    def _collector(self):
        collector = UsageCollector()
        collector.add_response(_response(1000, 500), "gpt-4.1-mini")
        return collector

    def test_record_when_empty_then_skips_without_connecting(self):
        with patch("pipeline.utilities.usage_recorder._connect") as mock_connect:
            recorded = record_pipeline_usage(
                UsageCollector(),
                stage="summarize",
                data_source="wfp",
                doc_id="doc-1",
                query="summarize: Title",
            )
        assert recorded is False
        mock_connect.assert_not_called()

    def test_record_inserts_one_row_per_model_with_cost(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        with patch("pipeline.utilities.usage_recorder._connect", return_value=conn):
            recorded = record_pipeline_usage(
                self._collector(),
                stage="summarize",
                data_source="wfp",
                doc_id="doc-1",
                query="summarize: Title",
            )
        assert recorded is True
        cursor.execute.assert_called_once()
        _sql, params = cursor.execute.call_args.args
        # (search_id, query, filters, llm_model, prompt, completion, cost)
        assert params[1] == "summarize: Title"
        filters = json.loads(params[2])
        assert filters == {
            "type": "pipeline",
            "stage": "summarize",
            "data_source": "wfp",
            "doc_id": "doc-1",
            "calls": 1,
        }
        assert params[3] == "gpt-4.1-mini"
        assert params[4] == 1000
        assert params[5] == 500
        # 1000 * 0.0004/1k + 500 * 0.0016/1k
        assert params[6] == Decimal("0.001200")
        # Then the estimated footprint, in FOOTPRINT_ROW_COLUMNS order.
        footprint = estimate_footprint("gpt-4.1-mini", 500)
        assert params[7:] == (
            *footprint.energy_kwh,
            *footprint.gwp_kgco2eq,
            *footprint.water_l,
            None,  # every output token had an estimate
        )
        for column in FOOTPRINT_ROW_COLUMNS:
            assert column in _sql
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_collector_estimates_each_call_not_the_document_total(self):
        # EcoLogits counts each call's start-up, so two calls of 250 output
        # tokens are estimated as two calls, not as one of 500.
        collector = UsageCollector()
        collector.add_response(_response(10, 250), "gpt-4.1-mini")
        collector.add_response(_response(10, 250), "gpt-4.1-mini")
        collector.add_response(_response(10, 300), "nova-2-lite")
        entries = {e["llm_model"]: e for e in collector.entries()}
        one_call = estimate_footprint("gpt-4.1-mini", 250)
        assert entries["gpt-4.1-mini"]["energy_kwh_max"] == pytest.approx(
            2 * one_call.energy_kwh[1]
        )
        assert entries["gpt-4.1-mini"]["footprint_unestimated_tokens"] is None
        assert entries["nova-2-lite"]["energy_kwh_max"] is None
        assert entries["nova-2-lite"]["footprint_unestimated_tokens"] == 300

    def test_record_resets_collector(self):
        collector = self._collector()
        with patch(
            "pipeline.utilities.usage_recorder._connect", return_value=MagicMock()
        ):
            record_pipeline_usage(
                collector,
                stage="tag",
                data_source="wfp",
                doc_id="doc-1",
                query="tag: Title",
            )
        assert collector.entries() == []

    def test_record_when_db_unreachable_then_swallows(self):
        with patch(
            "pipeline.utilities.usage_recorder._connect",
            side_effect=RuntimeError("no db"),
        ):
            recorded = record_pipeline_usage(
                self._collector(),
                stage="tag",
                data_source="wfp",
                doc_id="doc-1",
                query="tag: Title",
            )
        assert recorded is False
