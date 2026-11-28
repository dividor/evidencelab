"""The text of a search result as a research agent reads it.

The agent cites search results as ``[n]``, the number its search tool puts in
front of each result. Report passages carry numbers of their own that look the
same to a model: paragraph numbers ("143. At the school level..."), footnote
markers ("[^94]") and the report's own bracketed references ("[12]"). Measured
on one ten-section brief (2026-11-25), Nova 2 Lite cited 20 numbers that were no
result: 18 were paragraph numbers printed in that section's own passages and
one a footnote marker.

``passage_for_agent`` removes those numbers from the copy of the passage the
agent reads, so the only numbers left to cite are the result numbers. The
stored source text, which readers see and which highlighting matches against,
is not changed.
"""

import json
import re

# Pipeline footnote references and their definitions' markers: "[^94]", with
# the space in front of them so "schools [^94] in" reads "schools in".
_FOOTNOTE_MARKER = re.compile(r"[ \t]*\[\^\d+\]")

# A report's own bracketed references: "[12]", "[3, 7]", "[4-6]", "[4–6]".
_BRACKETED_REFERENCE = re.compile(r"[ \t]*\[\d+(?:\s*[,–-]\s*\d+)*\]")

# A paragraph number: digits and a full stop opening a paragraph, at the start
# of the text or a line, after a heading breadcrumb ("-- Findings --  143. ...")
# or after the previous sentence's end ("...commodities.  163. Key ..."). The
# next word must start with a capital letter or an opening quote/bracket, so
# "in 2015. The" (a number inside a sentence) and "Table 3. Results" are kept.
_PARAGRAPH_NUMBER = re.compile(
    r"(^|\n|--[ \t]+|[.!?:;][ \t]+)[ \t]*\d{1,4}\.[ \t]+(?=[A-Z\"'(“‘])"
)


def passage_for_agent(text: str) -> str:
    """``text`` without paragraph numbers, footnote markers or bracketed
    references, for the research agent's copy of a search result."""
    cleaned = _FOOTNOTE_MARKER.sub("", text)
    cleaned = _BRACKETED_REFERENCE.sub("", cleaned)
    return _PARAGRAPH_NUMBER.sub(r"\1", cleaned)


def passage_title_with_fields(passage: dict) -> str:
    """Give the model the source title and its catalogued scope."""
    title = passage["title"]
    fields = passage.get("document_fields")
    if not fields:
        return title
    return f"{title} | Document fields: {json.dumps(fields, ensure_ascii=False)}"
