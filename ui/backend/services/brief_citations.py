"""Brief citations: the one place that maps and renumbers a brief's citations.

A brief section is researched by one deep-research run whose agent numbers
its sources from ``[1]``. This module owns everything that happens to those
numbers afterwards, so the stored brief, the screen, the Word export, the
Activity log and the citation check all carry the same numbers:

- **Originals** (``sections[].runs[]``): the agent's output of every run,
  exactly as returned, appended and never edited. The latest run of a section
  (and its current run, after a reject) is kept exact; up to
  ``RETAINED_TRIMMED_RUNS`` earlier runs keep their content, mapping and
  unresolved markers but only their *cited* source records without the
  excerpt text (``sourcesRetained = "cited-without-excerpt"``); older runs are
  dropped. The trim is recorded on the run, never silent.
- **Brief-wide source list** (``content.sources``): every source record an
  agent returned gets a permanent brief-unique id (``s1``, ``s2``…) keyed by
  chunk id; passages of the same chunk share one id across sections and runs.
  A record with no chunk id is rejected, never merged under a substitute key.
  Each run records the mapping from the agent's per-section numbers to these
  ids.
- **Renumbered** (``sections[].renumbered``, ``content.references``): the
  content with markers rewritten to reading-order numbers across the brief
  (first citation = 1), the References list, the grouping used and when it was
  computed. Recomputed by :func:`renumber` on every change. A marker with no
  source is rewritten to ``[?n]`` (``n`` = the agent's number): visible as
  literal text, listed as unresolved, never dropped.

Pure functions over the ``briefs.content`` JSON; the Brief Central routes and
the anonymous ``/brief/citations`` endpoint call them, and the conversion of
pre-format-2 briefs reuses them. Tests: ``tests/unit/test_brief_citations.py``.
"""

from typing import Any, Dict, Optional

from ui.backend.services.brief_citation_model import (
    ADJACENT_DUPLICATE_RE,
    BRIEF_SETTING_FIELDS,
    CITATION_RE,
    CITATIONS_VERSION,
    DISPLAY_FIELDS,
    FILLABLE_FIELDS,
    GROUPING_DOC_MULTIPLE,
    GROUPING_DOC_SINGLE,
    GROUPING_PASSAGE,
    GROUPINGS,
    MAX_CONTENT_CHARS,
    REASON_NO_CHUNK,
    REASON_NO_SOURCE,
    RETAINED_TRIMMED_RUNS,
    RUN_CURRENT,
    RUN_MODES,
    RUN_REJECTED,
    RUN_SUMMARY_FIELDS,
    RUN_SUPERSEDED,
    SECTION_STRUCTURE_FIELDS,
    SOURCES_EXACT,
    SOURCES_TRIMMED,
    UNRESOLVED_RE,
    BriefCitationError,
    BriefTooLargeError,
    LegacyBriefError,
    cited_numbers_in_order,
    collapse_adjacent_duplicates,
    current_run,
    find_run,
    find_section,
    is_visible,
    parse_marker_numbers,
    require_current_format,
    strip_leading_title,
    unresolved_markers,
)
from ui.backend.services.brief_citation_read import (
    display_sections,
    expand_for_read,
    run_detail,
    trace,
)
from ui.backend.services.brief_citation_runs import (
    apply_retention,
    apply_structure,
    check_size,
    display_numbering,
    record_run,
    register_sources,
    reject_run,
    renumber,
    set_grouping,
    set_highlights,
)

OP_RUN, OP_REJECT, OP_GROUPING, OP_STRUCTURE, OP_HIGHLIGHTS, OP_READ = (
    "run",
    "reject",
    "grouping",
    "structure",
    "highlights",
    "read",
)


def apply_op(
    content: Dict[str, Any], op: Dict[str, Any], now_ms: Optional[int] = None
) -> Dict[str, Any]:
    """Apply one citation operation to a brief held by the browser (anonymous
    mode), with exactly the semantics of the Brief Central endpoints.
    ``read`` changes nothing: it only produces the read model."""
    kind = op.get("type")
    if kind == OP_RUN:
        return record_run(content, op["sectionId"], op["run"], now_ms)
    if kind == OP_REJECT:
        return reject_run(content, op["sectionId"], op["runId"], now_ms)
    if kind == OP_GROUPING:
        return set_grouping(content, op["grouping"], now_ms)
    if kind == OP_STRUCTURE:
        return apply_structure(content, op["brief"], now_ms)
    if kind == OP_HIGHLIGHTS:
        return set_highlights(content, op["highlights"])
    if kind == OP_READ:
        require_current_format(content)
        return content
    raise BriefCitationError(f"Unknown operation: {kind!r}")


__all__ = [
    "ADJACENT_DUPLICATE_RE",
    "BRIEF_SETTING_FIELDS",
    "BriefCitationError",
    "BriefTooLargeError",
    "CITATIONS_VERSION",
    "CITATION_RE",
    "DISPLAY_FIELDS",
    "FILLABLE_FIELDS",
    "GROUPINGS",
    "GROUPING_DOC_MULTIPLE",
    "GROUPING_DOC_SINGLE",
    "GROUPING_PASSAGE",
    "LegacyBriefError",
    "MAX_CONTENT_CHARS",
    "OP_GROUPING",
    "OP_HIGHLIGHTS",
    "OP_READ",
    "OP_REJECT",
    "OP_RUN",
    "OP_STRUCTURE",
    "REASON_NO_CHUNK",
    "REASON_NO_SOURCE",
    "RETAINED_TRIMMED_RUNS",
    "RUN_CURRENT",
    "RUN_MODES",
    "RUN_REJECTED",
    "RUN_SUMMARY_FIELDS",
    "RUN_SUPERSEDED",
    "SECTION_STRUCTURE_FIELDS",
    "SOURCES_EXACT",
    "SOURCES_TRIMMED",
    "UNRESOLVED_RE",
    "apply_op",
    "apply_retention",
    "apply_structure",
    "check_size",
    "cited_numbers_in_order",
    "collapse_adjacent_duplicates",
    "current_run",
    "display_numbering",
    "display_sections",
    "expand_for_read",
    "find_run",
    "find_section",
    "is_visible",
    "parse_marker_numbers",
    "record_run",
    "register_sources",
    "reject_run",
    "renumber",
    "require_current_format",
    "run_detail",
    "set_grouping",
    "set_highlights",
    "strip_leading_title",
    "trace",
    "unresolved_markers",
]
