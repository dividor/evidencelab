"""Group and render an AI summary's resolved citations into a References list.

The search UI resolves the inline ``[N]`` citation markers an AI summary emits
into a References list *in the browser*: it groups the citations by document and
appends each cited chunk's page number. That logic lives in TypeScript at
``ui/frontend/src/utils/citations.ts`` (``buildGroupedReferences``) and
``ui/frontend/src/components/AiSummaryReferences.tsx`` (the ``p.<page>`` suffix).

The evaluation harness runs server-side and cannot reuse that TypeScript, so this
module ports the same grouping-and-page-number rendering to Python. Keeping the
two in lock-step means an evaluated summary's references match what a user sees
in search — including the page numbers that were previously missing on the eval
side.

The one deliberate deviation from the frontend: the ``[N]`` numbers are kept as
the model emitted them rather than renumbered to a sequential ``1..k`` run. The
harness leaves the inline markers in the summary body untouched, so the
References must keep the same original numbers to stay consistent with them.
"""

from typing import Any, Dict, List


def group_references(references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group flat citation references by document title, preserving order.

    Mirrors the frontend ``buildGroupedReferences``: repeated citations of the
    same document collapse into one group, in first-appearance order. Each group
    carries the document metadata plus the list of its cited ``[N]`` numbers and
    their page numbers.

    Args:
        references: Flat citation dicts (as built by the harness), each with at
            least ``number`` and optionally ``title``, ``organization``,
            ``year``, ``page_num``.

    Returns:
        One dict per document, in first-cited order, with keys ``title``,
        ``organization``, ``year`` and a ``refs`` list of ``{number, page_num}``.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for ref in references:
        title = ref.get("title") or ref.get("doc_id") or "Unknown"
        group = groups.get(title)
        if group is None:
            group = {
                "title": title,
                "organization": ref.get("organization"),
                "year": ref.get("year"),
                "refs": [],
            }
            groups[title] = group
            order.append(title)
        group["refs"].append(
            {"number": ref.get("number"), "page_num": ref.get("page_num")}
        )
    return [groups[title] for title in order]


def _render_ref(ref: Dict[str, Any]) -> str:
    """Render one citation as ``[N]`` with an optional ``p.<page>`` suffix.

    The page suffix is shown only for a truthy page number, matching the
    frontend, which renders ``p.{page_num}`` only when ``page_num`` is truthy —
    so an unknown page (``0`` or missing) shows no page at all.
    """
    page = ref.get("page_num")
    suffix = f" p.{page}" if page else ""
    return f"[{ref.get('number')}]{suffix}"


def _render_group(group: Dict[str, Any]) -> str:
    """Render one document group as ``Title, Org, Year | [N] p.X [M] p.Y``."""
    meta = ", ".join(
        str(part)
        for part in (group.get("title"), group.get("organization"), group.get("year"))
        if part
    )
    refs = " ".join(_render_ref(ref) for ref in group.get("refs", []))
    return f"{meta} | {refs}" if refs else meta


def render_reference_lines(references: List[Dict[str, Any]]) -> List[str]:
    """Render references as one text line per document group.

    Each line matches the search UI's References layout — the document metadata,
    then a ``|`` separator, then its cited ``[N]`` markers each with their page
    number (``Title, Org, Year | [N] p.X [M] p.Y``).
    """
    return [_render_group(group) for group in group_references(references)]
