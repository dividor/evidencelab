from pipeline.processors.parsing import parser_toc


def test_normalize_toc_mixed_levels_handles_numbered_hierarchy():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page i",
            "  [H2] 1. Introduction | page 1",
            "    [H3] 1.1 Background | page 2",
            "    [H3] 2. Evaluation findings | page 5",
            "      [H4] 2.1 Details | page 6",
        ]
    )
    normalized = parser_toc.normalize_toc_mixed_levels(toc).splitlines()

    assert normalized[0].startswith("[H1] Executive Summary")
    assert normalized[1].startswith("[H1] 1. Introduction")
    assert normalized[2].startswith("  [H2] 1.1 Background")
    assert normalized[3].startswith("[H1] 2. Evaluation findings")
    assert normalized[4].startswith("  [H2] 2.1 Details")


def test_normalize_toc_mixed_levels_does_not_promote_front_sections():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5 (i) [Front]",
            "  [H2] 1. Introduction | page 6 (ii) [Front]",
            "    [H3] 1.1 Background | page 7 (iii) [Front]",
        ]
    )
    normalized = parser_toc.normalize_toc_mixed_levels(toc).splitlines()

    assert normalized[0].startswith("[H1] Executive Summary")
    assert normalized[1].startswith("  [H2] 1. Introduction")
    assert normalized[2].startswith("    [H3] 1.1 Background")


def test_annotate_toc_with_front_matter_requires_three_romans():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5",
            "[H1] Introduction | page 7",
        ]
    )
    roman_labels = {5: "i", 6: "ii"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "[Front]" not in annotated

    roman_labels = {5: "i", 6: "ii", 7: "iii"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "[Front]" in annotated


def test_annotate_toc_with_front_matter_removes_invalid_front():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5 [Front]",
            "[H1] Introduction | page 7 [Front]",
        ]
    )
    roman_labels = {5: "I"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "[Front]" not in annotated


def test_annotate_toc_with_front_matter_allows_uppercase_if_no_lower_run():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5",
            "[H1] Introduction | page 7",
        ]
    )
    roman_labels = {5: "I", 6: "II", 7: "III"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "[Front]" in annotated


def test_annotate_toc_with_front_matter_ignores_uppercase_after_lower_run():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5",
            "[H1] Introduction | page 7",
            "[H1] Conclusions | page 10",
        ]
    )
    roman_labels = {5: "i", 6: "ii", 7: "iii", 10: "V"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "page 10 (V) [Front]" not in annotated


def test_annotate_toc_with_front_matter_stops_on_reset_to_i():
    toc = "\n".join(
        [
            "[H1] Executive Summary | page 5",
            "[H1] Introduction | page 7",
            "[H1] Results | page 10",
        ]
    )
    roman_labels = {5: "i", 6: "ii", 7: "iii", 10: "i"}
    annotated = parser_toc.annotate_toc_with_front_matter(toc, roman_labels, 30)
    assert "page 10 (i) [Front]" not in annotated
