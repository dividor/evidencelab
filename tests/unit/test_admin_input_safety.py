"""What anonymous visitors store must not run when an administrator views it.

Ratings and activity rows are written by anyone (page feedback and search
logging work without signing in) and read in the admin screens and Excel
exports. A screenshot that is really an SVG, a javascript: link, or a comment
starting with ``=`` would otherwise run in the administrator's browser or Excel.
"""

import io
import re

import openpyxl
import pytest
from pydantic import ValidationError

from ui.backend.auth.schemas import (
    ActivityCreate,
    ActivitySummaryUpdateAnonymous,
    RatingCreate,
)
from ui.backend.utils.excel_text import append_text_row

JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
SVG = "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+"


def _rating(**overrides):
    payload = {
        "rating_type": "page_feedback",
        "reference_id": "page",
        "score": 1,
    }
    payload.update(overrides)
    return RatingCreate(**payload)


def _activity(**overrides):
    payload = {"search_id": "s-1", "query": "food security"}
    payload.update(overrides)
    return ActivityCreate(**payload)


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------


def test_rating_when_screenshot_is_jpeg_then_accepted():
    rating = _rating(context={"screenshot": JPEG})
    assert rating.context["screenshot"] == JPEG


@pytest.mark.parametrize(
    "value",
    [
        SVG,
        "data:text/html;base64,PHNjcmlwdD4=",
        " DATA:image/svg+xml,<svg onload=alert(1)>",
        'data:image/png;base64,abc"><script>',
    ],
)
def test_rating_when_context_holds_non_raster_data_url_then_rejected(value):
    with pytest.raises(ValidationError):
        _rating(context={"screenshot": value})


@pytest.mark.parametrize(
    "value",
    ["javascript:alert(1)", " JavaScript:alert(1)", "java\tscript:x", "vbscript:x"],
)
def test_rating_when_link_field_is_script_url_then_rejected(value):
    with pytest.raises(ValidationError):
        _rating(context={"link": value})
    with pytest.raises(ValidationError):
        _rating(context={"report_url": value})
    with pytest.raises(ValidationError):
        _rating(url=value)


def test_rating_when_script_url_nested_in_results_then_rejected():
    with pytest.raises(ValidationError):
        _rating(context={"results": [{"title": "t", "link": "javascript:x"}]})


def test_rating_when_comment_mentions_javascript_then_kept_as_text():
    """Free text is shown as text, so it is not second-guessed."""
    rating = _rating(comment="javascript: tutorials are missing", url="https://x.org/a")
    assert rating.comment.startswith("javascript:")


def test_rating_when_links_are_web_or_site_paths_then_accepted():
    rating = _rating(
        url="https://evidencelab.ai/?q=x",
        context={"link": "/api/pdf/1", "pdf_url": "https://example.org/a.pdf"},
    )
    assert rating.context["link"] == "/api/pdf/1"


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


def test_activity_when_result_link_is_script_url_then_rejected():
    with pytest.raises(ValidationError):
        _activity(search_results=[{"title": "t", "link": "javascript:alert(1)"}])


def test_activity_when_url_is_script_url_then_rejected():
    with pytest.raises(ValidationError):
        _activity(url="javascript:alert(1)")


def test_activity_when_results_are_normal_then_accepted():
    activity = _activity(
        search_results=[
            {"title": "javascript: guide", "link": "https://example.org/a"}
        ],
        url="https://evidencelab.ai/?q=food",
    )
    assert activity.search_results[0]["title"] == "javascript: guide"


def test_activity_summary_when_tree_holds_svg_data_url_then_rejected():
    with pytest.raises(ValidationError):
        ActivitySummaryUpdateAnonymous(drilldown_tree={"image": SVG})


# ---------------------------------------------------------------------------
# Excel exports
# ---------------------------------------------------------------------------


def test_append_text_row_when_value_looks_like_formula_then_saved_as_text():
    book = openpyxl.Workbook()
    sheet = book.active
    append_text_row(sheet, ['=HYPERLINK("https://x.org","click")', "plain", 3])

    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    reloaded = openpyxl.load_workbook(buffer).active

    cells = list(reloaded[1])
    assert cells[0].value == '=HYPERLINK("https://x.org","click")'
    assert cells[0].data_type == "s"
    assert cells[1].value == "plain"
    assert cells[2].value == 3


def test_exports_when_built_then_every_builder_uses_text_rows():
    """No export builds rows with a bare ``append`` that could write a formula."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "ui" / "backend"
    builders = [
        root / "routes" / "ratings.py",
        root / "routes" / "activity.py",
        root / "routes" / "llm_usage.py",
        root / "services" / "citation_fidelity.py",
    ]
    for path in builders:
        source = path.read_text()
        assert "append_text_row(" in source, path.name
        assert not re.search(r"\b(ws|sheet)\.append\(", source), path.name
