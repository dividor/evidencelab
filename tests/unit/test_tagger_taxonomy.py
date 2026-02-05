import json
import os
from unittest.mock import MagicMock, patch

import pytest

from pipeline.processors.tagging.tagger_taxonomy import TaxonomyTagger


class TestTaxonomyTagger:
    """Unit tests for TaxonomyTagger using real configuration."""

    @pytest.fixture
    def real_config(self):
        """Load the actual config.json from the repository."""
        config_path = os.path.join(os.path.dirname(__file__), "../../config.json")
        with open(config_path, "r") as f:
            return json.load(f)

    @pytest.fixture
    def tagger(self, real_config):
        """Initialize TaxonomyTagger with the UNEG pipeline configuration."""
        # Extract the specific tagging configuration used for UNEG datasource
        tagging_config = real_config["datasources"][
            "UN Humanitarian Evaluation Reports"
        ]["pipeline"]["tag"]

        with patch(
            "pipeline.processors.tagging.tagger_taxonomy.Database"
        ) as mock_db_cls:
            mock_db = mock_db_cls.return_value
            tagger = TaxonomyTagger(config=tagging_config)
            tagger.set_db(mock_db)
            return tagger

    def test_initialization(self, tagger):
        """Test tagger initializes correctly with real config."""
        assert tagger.name == "TaxonomyTagger"
        # Verify it loaded the SDG taxonomy from the real config
        assert "sdg" in tagger.taxonomies_config
        assert (
            tagger.taxonomies_config["sdg"]["name"]
            == "United Nations Sustainable Development Goals"
        )

    @patch("pipeline.processors.tagging.tagger_taxonomy.get_llm")
    def test_prioritize_full_summary(self, mock_get_llm, tagger):
        """Test that sys_full_summary is used when available, using real taxonomy keys."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        # Mock LLM response with structured list
        mock_response = MagicMock()
        # Using 'sdg1' which exists in config.json
        mock_response.content = json.dumps(
            [
                {"code": "sdg1", "reason": "Explicit mention of poverty."},
                {
                    "code": "sdg5",
                    "reason": "Mention of women.",
                },  # Assuming sdg5 is invalid for this test setup if not in filter?
                # Wait, sdg5 IS in values. So both should be active if I didn't filter in assertion.
                # Let's just use one for simplicity or verify both.
            ]
        )
        mock_llm.invoke.return_value = mock_response

        document = {
            "id": "doc1",
            "sys_summary": "Short summary",
            "sys_full_summary": "This is a full detailed summary about poverty.",
        }

        # Mock cache miss
        tagger._database.get_cached_taxonomy.return_value = None

        tags = tagger.compute_document_tags(document)

        # Verify LLM was called with the full summary
        args, _ = mock_llm.invoke.call_args
        prompt_text = args[0][1].content  # User prompt
        assert "This is a full detailed summary about poverty." in prompt_text
        assert "Short summary" not in prompt_text

        # Verify result map matches enriched taxonomy values
        # New format: list of dicts with code, name, reason
        sdg_values = tags["sys_taxonomies"]["sdg"]
        assert len(sdg_values) == 2
        assert any(
            v["code"] == "sdg1" and v["name"] == "No Poverty" for v in sdg_values
        )
        assert any(
            v["code"] == "sdg5" and v["name"] == "Gender Equality" for v in sdg_values
        )
        # Verify reasons are captured
        assert all("reason" in v for v in sdg_values)

    @patch("pipeline.processors.tagging.tagger_taxonomy.get_llm")
    def test_no_fallback_to_short_summary(self, mock_get_llm, tagger):
        """Test that sys_summary is IGNORED if full summary is missing."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        document = {
            "id": "doc1",
            "sys_summary": "Short summary about hunger.",
            # sys_full_summary missing
        }

        tagger._database.get_cached_taxonomy.return_value = None

        tags = tagger.compute_document_tags(document)

        # Verify LLM was NOT called
        mock_llm.invoke.assert_not_called()

        # Should be empty
        assert tags == {}

    def test_empty_summary_returns_empty(self, tagger):
        """Test that empty summaries result in empty tags without calling LLM."""
        document = {"id": "doc1", "sys_summary": "", "sys_full_summary": None}

        tags = tagger.compute_document_tags(document)
        assert tags == {}

    @patch("pipeline.processors.tagging.tagger_taxonomy.get_llm")
    def test_llm_json_parsing_error(self, mock_get_llm, tagger):
        """Test handling of malformed JSON from LLM."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        mock_response = MagicMock()
        mock_response.content = "Not JSON"
        mock_llm.invoke.return_value = mock_response

        document = {"id": "doc1", "sys_full_summary": "Content"}
        tagger._database.get_cached_taxonomy.return_value = None

        tags = tagger.compute_document_tags(document)

        # Wrapped fallback return
        assert tags == {"sys_taxonomies": {}}

    @patch("pipeline.processors.tagging.tagger_taxonomy.get_llm")
    def test_prompt_construction(self, mock_get_llm, tagger):
        """Test that the prompt contains actual taxonomy definitions from config."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_llm.invoke.return_value.content = "{}"

        document = {"id": "1", "sys_full_summary": "Text"}
        tagger._database.get_cached_taxonomy.return_value = None

        tagger.compute_document_tags(document)

        args, _ = mock_llm.invoke.call_args
        messages = args[0]
        system_prompt = messages[0].content
        user_prompt = messages[1].content

        # Verify values from real config are present
        assert "United Nations Sustainable Development Goals" in system_prompt
        # Check for a specific SDG definition likely to exist
        assert "No Poverty" in user_prompt
        assert "End poverty in all its forms everywhere" in user_prompt

        # Verify duplication is removed
        # The prompt construction:
        # line = f"- Code: {code}\n  Name: {name}\n  Definition: {definition}\n"
        # if question: line += f"  Question: {question}\n"

        # We need to ensure that detailed definition text does NOT appear twice in the same block
        # This is harder to regex without exact string, but check for
        # Check that the template renders correctly with proper headings
        # In config schema for sdg1:
        # Definition: "End poverty in all its forms..."
        # llm_prompt: "Assign SDG 1 if the document discusses: (1) Extreme poverty..."

        # Verify template headings are present
        assert "Definition:" in user_prompt
        assert "Evaluation Criteria:" in user_prompt
