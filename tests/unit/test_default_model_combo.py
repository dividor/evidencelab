"""The default model combo must reach the UI, and mean the same thing everywhere.

`config.json` marks the starting combo with `ui_model_combos.<name>.default`.
`pipeline.db.get_default_model_combo()` honours it, and so do the evaluation
harness and the A2A server — but the `/config/model-combos` response model had
no such field, so Pydantic dropped it and the UI started on whichever combo
came first in the file instead. These tests pin both halves.
"""

import pytest

from ui.backend.schemas import ModelComboConfig

pytestmark = pytest.mark.unit


def _summary_model():
    return {
        "model": "m",
        "max_tokens": 1024,
        "temperature": 0.0,
        "chunk_overlap": 0,
        "chunk_tokens_ratio": 1.0,
    }


def _combo(**overrides):
    base = {
        "embedding_model": "e5_large",
        "summarization_model": _summary_model(),
        "semantic_highlighting_model": _summary_model(),
        "reranker_model": "none",
    }
    base.update(overrides)
    return base


class TestResponseModel:
    def test_model_combo_when_flagged_default_then_the_flag_survives(self):
        parsed = ModelComboConfig(**_combo(default=True))
        assert parsed.default is True, (
            "The response model dropped the default flag, so the UI cannot see "
            "which combo config.json marks as the starting one."
        )

    def test_model_combo_when_not_flagged_then_default_is_absent(self):
        assert ModelComboConfig(**_combo()).default is None

    def test_model_combo_when_serialised_then_the_flag_is_included(self):
        dumped = ModelComboConfig(**_combo(default=True)).model_dump()
        assert dumped["default"] is True


class TestBackendResolution:
    """The behaviour the UI is being brought in line with."""

    @staticmethod
    def _resolve(combos):
        import pipeline.db.config as cfg

        original = cfg.UI_MODEL_COMBOS
        cfg.UI_MODEL_COMBOS = combos
        try:
            return cfg.get_default_model_combo()
        finally:
            cfg.UI_MODEL_COMBOS = original

    def test_default_combo_when_one_is_flagged_then_it_is_chosen(self):
        assert self._resolve({"A": {}, "B": {"default": True}}) == "B"

    def test_default_combo_when_none_flagged_then_the_first_is_chosen(self):
        assert self._resolve({"A": {}, "B": {}}) == "A"

    def test_default_combo_when_no_combos_then_empty(self):
        assert self._resolve({}) == ""
