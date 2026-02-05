import re

from pipeline.processors.parsing import parser_superscripts


class DummyParser:
    def __init__(self, superscript_mode: str = "caret"):
        self.superscript_mode = superscript_mode


class DummyItem:
    def __init__(self, text: str):
        self.text = text


class DummyDocument:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        for item in self._items:
            yield item, None


def test_build_regex_pattern_matches_token():
    pattern = parser_superscripts._build_regex_pattern("word", "1", "next")

    assert re.search(pattern, "word1 next")


def test_build_superscript_rule_detects_elevation():
    spans = [
        {"text": "word", "size": 10, "font": "Times", "origin": (0, 100)},
        {"text": "1", "size": 6, "font": "Times", "origin": (0, 90)},
        {"text": "next", "size": 10, "font": "Times", "origin": (0, 100)},
    ]
    rule = parser_superscripts._build_superscript_rule(
        spans, 1, median_size=10, block_ref_y=100, use_baseline=True
    )

    assert rule is not None
    pattern, token = rule
    assert token == "1"
    assert re.search(pattern, "word1 next")


def test_apply_superscripts_to_markdown(tmp_path):
    markdown_path = tmp_path / "doc.md"
    markdown_path.write_text("word1 next\n1 heading", encoding="utf-8")
    pattern = parser_superscripts._build_regex_pattern("word", "1", "next")
    superscripts = {1: [(pattern, "1")]}
    parser = DummyParser("caret")

    parser_superscripts.apply_superscripts_to_markdown(
        parser, markdown_path, superscripts
    )

    updated = markdown_path.read_text(encoding="utf-8")
    assert "word^1 next" in updated
    assert updated.splitlines()[1].startswith("^1 ")


def test_apply_superscripts_to_docling_items():
    pattern = parser_superscripts._build_regex_pattern("word", "1", "next")
    superscripts = {1: [(pattern, "1")]}
    parser = DummyParser("caret")
    item = DummyItem("word1 next")
    document = DummyDocument([item])

    parser_superscripts.apply_superscripts_to_docling_items(
        parser, document, superscripts
    )

    assert item.text == "word^1 next"
