"""A chunk's text must survive post-processing.

Chunk elements are built only from provenance entries that carry a bounding
box. A document with no page geometry — every .docx and .doc — has none, so
rebuilding a chunk's text from its elements yields an empty string. Doing that
unconditionally destroyed the text of such documents: a 8,477-word Word file
produced 33 good chunks, all of which were emptied here, deduplicated down to
one, and then discarded by the indexer.
"""

import pytest

from pipeline.processors.indexing.chunker_post import post_process_chunks


class _Doc:
    """Minimal stand-in for a document with no footnotes."""

    texts: list = []
    tables: list = []
    pictures: list = []

    def iterate_items(self, *args, **kwargs):
        return iter(())


@pytest.fixture
def doc():
    return _Doc()


def _chunk(text, elements=None, headings=None):
    return {
        "text": text,
        "chunk_elements": elements if elements is not None else [],
        "headings": headings or [],
        "page_num": 1,
        "chunk_index": 0,
    }


def test_text_survives_when_there_are_no_elements(doc):
    chunks = [_chunk("The evaluation found substantial progress on gender equality.")]

    post_process_chunks(doc, chunks)

    assert "substantial progress on gender equality" in chunks[0]["text"]


def test_every_chunk_of_a_page_less_document_keeps_distinct_text(doc):
    """Emptied chunks collapse to one in deduplication, so the document is lost."""
    chunks = [_chunk(f"Section {n} of the evaluation report.") for n in range(5)]

    post_process_chunks(doc, chunks)

    texts = {c["text"] for c in chunks}
    assert len(texts) == 5, f"chunks collapsed to {len(texts)} distinct text(s)"
    assert all(c["text"].strip() for c in chunks)


def test_a_rebuild_with_content_still_replaces_the_text(doc):
    """The rebuild is what adds footnotes and ordering; it must still apply."""
    elements = [
        {"element_type": "text", "text": "Rebuilt body text.", "label": "text"},
    ]
    chunks = [_chunk("original text", elements=elements)]

    post_process_chunks(doc, chunks)

    assert "Rebuilt body text." in chunks[0]["text"]
    assert "original text" not in chunks[0]["text"]


def test_headings_are_still_prefixed_when_the_text_is_kept(doc):
    chunks = [_chunk("Body of the section.", headings=["Findings"])]

    post_process_chunks(doc, chunks)

    assert "Findings" in chunks[0]["text"]
    assert "Body of the section." in chunks[0]["text"]
