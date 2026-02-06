"""
Unit tests for TOC section type classification.

These tests call the actual LLM classification pipeline and verify results.
Requires HUGGINGFACE_API_KEY to be set.
"""

import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.processors.tagging.tagger import SectionTypeTagger

pytestmark = pytest.mark.skipif(
    not os.environ.get("HUGGINGFACE_API_KEY"),
    reason="HUGGINGFACE_API_KEY not set",
)

# Test data: document -> {toc: [(heading_line, expected_category), ...], num_pages}
TEST_DOCUMENTS = {
    "Independent Country Programme Evaluation: Liberia - Main Report": {
        "toc": [
            (
                "[H2] INDEPENDENT COUNTRY PROGRAMME EVALUATION LIBERIA | page 1",
                "other",
            ),
            (
                "[H2] LIBERIA INDEPENDENT COUNTRY PROGRAMME EVALUATION | page 2",
                "other",
            ),
            (
                "[H3] REPORTS PUBLISHED UNDER THE ICPE SERIES | page 3 [Front]",
                "front_matter",
            ),
            (
                "[H4] INDEPENDENT COUNTRY PROGRAMME EVALUATION: Liberia | page 3 [Front]",
                "front_matter",
            ),
            ("[H3] ACKNOWLEDGEMENTS | page 4 [Front]", "front_matter"),
            ("[H4] IEO TEAM | page 4 [Front]", "front_matter"),
            ("[H4] STAKEHOLDERS AND PARTNERS | page 4 [Front]", "front_matter"),
            ("[H3] CONTENTS | page 5 [Front]", "front_matter"),
            ("[H4] BOXES | page 6 [Front]", "front_matter"),
            ("[H3] ACRONYMS | page 7", "acronyms"),
            ("[H4] Evaluation Brief: Liberia | page 8", "executive_summary"),
            ("[H5] Recommendations | page 9", "executive_summary"),
            ("[H3] BACKGROUND AND INTRODUCTION CHAPTER 1 | page 10", "introduction"),
            (
                "[H4] 1.1 Purpose, objectives, and scope of the evaluation | page 11",
                "introduction",
            ),
            ("[H5] BOX 1. Evaluation questions | page 11", "introduction"),
            ("[H4] 1.2 Evaluation methodology | page 11", "introduction"),
            ("[H4] 1.3 Evaluation limitations | page 12", "introduction"),
            ("[H4] 1.4 Context | page 12", "introduction"),
            (
                "[H4] 1.5 UNDP in Liberia and country programme under review | page 14",
                "introduction",
            ),
            (
                "[H4] 2.1 Programme responsiveness and coherence | page 19",
                "introduction",
            ),
            (
                "[H4] 2.2 UNDP's contributions to programme objectives "
                "and sustainable development res | page 22",
                "introduction",
            ),
            (
                "[H5] Inclusive, Effective, Transparent, and Accountable Governance "
                "- linked to CPD Ou | page 22",
                "introduction",
            ),
            (
                "[H5] 2023 Elections: Facts, figures, and main achievements | page 27",
                "introduction",
            ),
            (
                "[H5] Bringing essential public services closer to the people: "
                "Decentralized service d | page 28",
                "introduction",
            ),
            (
                "[H5] Strengthening of local service delivery: Gender-based violence (GBV) "
                "prevention  | page 30",
                "introduction",
            ),
            (
                "[H5] Accessibility and efficiency of a strengthened justice system and "
                "alternative di | page 32",
                "introduction",
            ),
            (
                "[H5] Trust building through effective delivery of essential security and "
                "protection s | page 34",
                "introduction",
            ),
            (
                "[H5] Mainstreaming energy and environment and inclusive green growth "
                "- linked to CPD  | page 36",
                "introduction",
            ),
            (
                "[H4] 2.3 Factors influencing programme performance and cross-cutting issues "
                "| page 44",
                "introduction",
            ),
            (
                "[H3] CONCLUSIONS, RECOMMENDATIONS, AND MANAGEMENT RESPONSE CHAPTER 3 | page 51",
                "recommendations",
            ),
            ("[H4] 3.1 Conclusions | page 52", "conclusions"),
            ("[H4] 3.2 Recommendations | page 55", "recommendations"),
            (
                "[H4] 3.3 Key Recommendations and Management Response | page 58",
                "recommendations",
            ),
            ("[H5] Management response: Accepted | page 58", "recommendations"),
            ("[H5] Management response: Accepted | page 59", "recommendations"),
            ("[H5] Management response: Accepted | page 60", "recommendations"),
            ("[H5] Management response: Accepted | page 61", "recommendations"),
            ("[H5] Management response: Accepted | page 62", "recommendations"),
            ("[H5] Management response: Accepted | page 63", "recommendations"),
            ("[H4] ANNEXES | page 64", "annexes"),
        ],
        "num_pages": 65,
    },
    "Evaluation of the project on building the Pan-Asia partnership - Brief": {
        "toc": [
            ("[H2] Background | page 1", "executive_summary"),
            ("[H2] Key facts | page 1", "executive_summary"),
            ("[H2] Evaluation Purpose and Methodology | page 1", "executive_summary"),
            ("[H2] Evaluation Brief | page 1", "executive_summary"),
            (
                "[H3] Building the Pan-Asia Partnership for Geospatial Air Pollution | page 1",
                "executive_summary",
            ),
            ("[H4] Main Findings | page 1", "executive_summary"),
            ("[H5] Impact | page 1", "executive_summary"),
            ("[H6] Relevance | page 1", "executive_summary"),
            ("[H6] Effectiveness | page 1", "executive_summary"),
            ("[H6] Efficiency | page 2", "executive_summary"),
            ("[H6] Sustainability | page 2", "executive_summary"),
            ("[H6] Gender Mainstreaming | page 2", "executive_summary"),
            ("[H6] Lessons Learned | page 2", "executive_summary"),
            ("[H4] Recommendations | page 2", "executive_summary"),
        ],
        "num_pages": 3,
    },
}


def extract_heading_from_line(line: str) -> str:
    """Extract heading text from TOC line like '[H2] Title | page 1 [Front]'."""
    match = re.match(
        r"^\[H\d\]\s*(.+?)\s*\|\s*page\s*\d+(?:\s*\([^)]+\))?\s*(?:\[Front\])?\s*$",
        line,
    )
    if match:
        return match.group(1).strip()
    return ""


def parse_toc_classified(toc_classified: str) -> dict:
    """Parse toc_classified string into {heading: section_type} dict."""
    result = {}
    for line in toc_classified.split("\n"):
        match = re.match(
            r"^\s*\[H\d\]\s*(.+?)\s*\|\s*([a-z_]+)\s*(?:\|\s*page\s*\d+)?$", line
        )
        if match:
            title = match.group(1).strip()
            section_type = match.group(2).strip()
            result[title] = section_type
    return result


@pytest.fixture(scope="module")
def section_tagger():
    """Create SectionTypeTagger without embedding model."""
    config_path = Path(__file__).resolve().parents[2] / "config.json"
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    datasource = config["datasources"]["UN Humanitarian Evaluation Reports"]
    tag_config = datasource["pipeline"]["tag"]
    tagger = SectionTypeTagger(llm_config=tag_config)
    tagger.setup()
    return tagger


class TestTOCClassification:
    """Test TOC classification pipeline."""

    @pytest.mark.parametrize("doc_title", list(TEST_DOCUMENTS.keys()))
    def test_document_classification(self, section_tagger, doc_title):
        """Test LLM classification matches expected categories."""
        doc_data = TEST_DOCUMENTS[doc_title]
        toc_entries = doc_data["toc"]
        # num_pages = doc_data["num_pages"]

        # Build TOC string from entries
        toc_lines = [entry[0] for entry in toc_entries]
        toc_string = "\n".join(toc_lines)

        # Call classification via public API (with mocked DB to avoid errors)
        document = {
            "id": "test_doc",
            "map_title": doc_title,
            "sys_toc": toc_string,
            "sys_page_count": doc_data.get(
                "num_pages"
            ),  # Include page_count for front matter boundary rule
        }

        # We need to mock the DB inside tagger because classify_document_toc tries to save results
        section_tagger._database = MagicMock()
        section_tagger._document_cache = {}

        # return is legacy mapping: normalized_title -> label
        legacy_mapping = section_tagger.classify_document_toc(document)

        # We need to reconstruct the "toc_classified" string or just verify the mapping.
        # The test expects to verify line by line.
        # We can map the legacy_mapping back to lines.

        # Check each row
        errors = []
        for toc_line, expected_category in toc_entries:
            heading = extract_heading_from_line(toc_line)
            # Normalize heading to match tagger output keys (lowercase, stripped)
            norm_heading = heading.lower().strip()

            if norm_heading not in legacy_mapping:
                errors.append(f"Missing: {heading} (normalized: {norm_heading})")
            elif legacy_mapping[norm_heading] != expected_category:
                errors.append(
                    f"'{heading}': expected '{expected_category}', "
                    f"got '{legacy_mapping[norm_heading]}'"
                )

        if errors:
            pytest.fail("\n".join(errors))
