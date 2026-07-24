"""Unit tests for Brief section AI Edit — the surgical single-LLM revise
(``ui.backend.services.llm_service.revise_brief_section`` + ``_strip_section_wrapper``)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.backend.services.llm_service import _strip_section_wrapper, revise_brief_section

pytestmark = pytest.mark.unit


class TestStripSectionWrapper:
    def test_strips_language_code_fence(self):
        assert (
            _strip_section_wrapper("```markdown\n# Title\n\nBody.\n```")
            == "# Title\n\nBody."
        )

    def test_strips_bare_code_fence(self):
        assert _strip_section_wrapper("```\nBody.\n```") == "Body."

    def test_strips_triple_quote_wrapper(self):
        assert _strip_section_wrapper('"""\nBody.\n"""') == "Body."

    def test_leaves_plain_markdown_untouched(self):
        md = "## Heading\n\nA claim [1]."
        assert _strip_section_wrapper(md) == md


class TestReviseBriefSection:
    @staticmethod
    def _mock_llm(content: str):
        fake_response = MagicMock()
        fake_response.content = content
        fake_llm = MagicMock()
        fake_llm.ainvoke = AsyncMock(return_value=fake_response)
        return fake_llm

    @pytest.mark.asyncio
    async def test_sends_instruction_and_content_without_html_escaping(self):
        # The model HTML-escapes a quote in its output; the stored section must be
        # cleaned (entities decoded), and the PROMPT must not escape the content.
        fake_llm = self._mock_llm("The report says &#34;free and compulsory&#34; [1].")
        with patch(
            "ui.backend.services.llm_service.get_llm", return_value=fake_llm
        ) as mock_get_llm:
            result = await revise_brief_section(
                content='Article 53 declares basic education "free and compulsory" [1].',
                instruction="Make it more concise",
                model_key="some-model",
            )

        mock_get_llm.assert_called_once()
        assert mock_get_llm.call_args.kwargs["model"] == "some-model"
        sent = fake_llm.ainvoke.call_args.args[0]
        joined = " ".join(str(m.content) for m in sent)
        # Instruction + content both reach the LLM.
        assert "Make it more concise" in joined
        assert "free and compulsory" in joined
        # Autoescape is neutralised (Markup/unescape) so quotes are NOT sent as
        # entities that the model would echo back.
        assert "&#34;" not in joined
        # Output entities are decoded so the stored markdown is clean.
        assert result == 'The report says "free and compulsory" [1].'

    @pytest.mark.asyncio
    async def test_strips_code_fence_from_output(self):
        fake_llm = self._mock_llm("```markdown\nRevised body [1].\n```")
        with patch("ui.backend.services.llm_service.get_llm", return_value=fake_llm):
            result = await revise_brief_section(
                content="Body [1].", instruction="tighten", model_key="m"
            )
        assert result == "Revised body [1]."
