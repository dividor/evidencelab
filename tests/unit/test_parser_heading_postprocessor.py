"""The heading-level add-in must leave numbered body text alone.

From version 0.1.6, docling-hierarchical-pdf treats numbered list items
("1. The strategic evaluation provides…", "i) How relevant is…") as headings.
On a WFP evaluation that filed chapter 1 under the Executive Summary, flattened
the real headings and changed the chunks. Evidence Lab holds the add-in at the
version its existing library was parsed with. These tests run the real add-in
through the parser's heading step on a small document with no bookmarks, and
fail if list items become headings or real headings lose their levels.
"""

from types import SimpleNamespace

import pymupdf
import pytest
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    ProvenanceItem,
    Size,
)
from docling_core.types.doc.document import ListItem, SectionHeaderItem

from pipeline.processors.parsing.parser_headings import apply_hierarchical_postprocessor

HEADINGS = [
    ("Executive Summary", 1, 760, 14),
    ("Introduction and evaluation features", 2, 730, 12),
]
LIST_ITEMS = [
    (
        "1.",
        "The strategic evaluation provides a formative and forward-looking assessment.",
    ),
    ("i)", "How relevant is WFP's resilience work and for whom?"),
]
CONTEXT = ("Context", 3, 560, 11)


def _prov(top: float, height: float) -> ProvenanceItem:
    bbox = BoundingBox(
        l=50, t=top, r=550, b=top - height, coord_origin=CoordOrigin.BOTTOMLEFT
    )
    return ProvenanceItem(page_no=1, bbox=bbox, charspan=(0, 1))


def _conversion(pdf_path) -> SimpleNamespace:
    """A conversion result as the parser holds it after Docling, before the add-in.

    The page has no layout predictions, so the add-in reads heading sizes from
    the document's own provenance, as it does when cell geometry is missing.
    """
    doc = DoclingDocument(name="report")
    doc.add_page(page_no=1, size=Size(width=600, height=800))
    for text, level, top, height in HEADINGS:
        doc.add_heading(text=text, level=level, prov=_prov(top, height))
    group = doc.add_list_group(name="list")
    for i, (marker, text) in enumerate(LIST_ITEMS):
        doc.add_list_item(
            text=text,
            enumerated=True,
            marker=marker,
            orig=f"{marker} {text}",
            parent=group,
            prov=_prov(700 - 60 * i, 40),
        )
    text, level, top, height = CONTEXT
    doc.add_heading(text=text, level=level, prov=_prov(top, height))
    page = SimpleNamespace(predictions=SimpleNamespace(layout=None), size=None)
    return SimpleNamespace(
        document=doc, pages=[page], input=SimpleNamespace(file=pdf_path)
    )


@pytest.fixture
def blank_pdf(tmp_path):
    """A one-page PDF with no bookmarks, the source the add-in reads its outline from."""
    path = tmp_path / "report.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    return path


def _items(result, kind):
    return [
        item for item, _ in result.document.iterate_items() if isinstance(item, kind)
    ]


@pytest.mark.unit
def test_heading_postprocessor_when_numbered_list_items_then_they_stay_list_items(
    blank_pdf,
):
    result = _conversion(blank_pdf)

    apply_hierarchical_postprocessor(None, result, blank_pdf)

    headings = [h.text for h in _items(result, SectionHeaderItem)]
    assert headings == [h[0] for h in HEADINGS] + [CONTEXT[0]]
    assert [i.text for i in _items(result, ListItem)] == [
        text for _, text in LIST_ITEMS
    ]


@pytest.mark.unit
def test_heading_postprocessor_when_headings_nest_then_levels_keep_their_order(
    blank_pdf,
):
    result = _conversion(blank_pdf)

    apply_hierarchical_postprocessor(None, result, blank_pdf)

    levels = {h.text: h.level for h in _items(result, SectionHeaderItem)}
    assert levels["Executive Summary"] < levels["Introduction and evaluation features"]
