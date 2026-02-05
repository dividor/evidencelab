from pipeline.processors.parsing import parser_headings


class SectionHeaderItem:
    def __init__(self, text: str, level: int):
        self.text = text
        self.level = level


class DummyDocument:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        for item in self._items:
            yield item, None


class DummyResult:
    def __init__(self, items):
        self.document = DummyDocument(items)


def test_check_if_hierarchy_exists_true():
    items = [SectionHeaderItem("Intro", 1), SectionHeaderItem("Methods", 2)]
    result = DummyResult(items)

    assert parser_headings.check_if_hierarchy_exists(result) is True


def test_check_if_hierarchy_exists_false_when_flat():
    items = [SectionHeaderItem("Intro", 1), SectionHeaderItem("Methods", 1)]
    result = DummyResult(items)

    assert parser_headings.check_if_hierarchy_exists(result) is False


def test_infer_level_from_numbering_handles_patterns():
    assert parser_headings.infer_level_from_numbering("1.2.3 Title") == 3
    assert parser_headings.infer_level_from_numbering("Figure 2") == 3
    assert parser_headings.infer_level_from_numbering("Appendix") is None


def test_determine_heading_level_prefers_font_thresholds():
    level, method = parser_headings._determine_heading_level(
        "Heading", dominant_size=20, body_size=11, top_sections=set()
    )

    assert level == 2
    assert method == "font"


def test_determine_heading_level_uses_keywords():
    top_sections = {"introduction"}
    level, method = parser_headings._determine_heading_level(
        "Introduction", dominant_size=12, body_size=12, top_sections=top_sections
    )

    assert level == 1
    assert method == "keyword"


def test_apply_heading_map_updates_levels():
    headings = [{"text": "Intro", "level": 1}]
    heading_map = parser_headings._build_heading_map(headings)

    items = [SectionHeaderItem("Intro", 3)]
    result = DummyResult(items)

    updated = parser_headings._apply_heading_map(result, heading_map)

    assert updated == 1
    assert items[0].level == 1
