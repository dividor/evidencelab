"""
test_basic.py - Basic tests for pipeline helper utilities.
"""

from datetime import datetime

from pipeline.processors.indexing.indexer import (
    add_passage_prefix,
    is_e5_model,
    year_to_unix,
)


def test_is_e5_model_detection():
    assert is_e5_model("intfloat/multilingual-e5-large")
    assert is_e5_model("E5-small")
    assert not is_e5_model("bge-large")


def test_add_passage_prefix_for_e5_models():
    text = "sample passage"
    assert add_passage_prefix(text, "e5-base") == "passage: sample passage"


def test_add_passage_prefix_for_non_e5_models():
    text = "sample passage"
    assert add_passage_prefix(text, "bge-large-en") == text


def test_year_to_unix_valid_year():
    expected = int(datetime(2024, 1, 1, 0, 0, 0).timestamp())
    assert year_to_unix("2024") == expected


def test_year_to_unix_invalid_year():
    assert year_to_unix("not-a-year") is None
    assert year_to_unix(None) is None
