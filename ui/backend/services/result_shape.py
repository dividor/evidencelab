"""Which parts of its document record a search result carries.

Every ``/search`` result joins a chunk to its document record. Sending the
whole record on every chunk made a 1000-result response 140 MB or more, 93 %
of it in a few keys no reader uses: the raw pipeline record (``sys_data``),
the table of contents, the taxonomies, the raw source metadata (already
unpacked into ``src_*`` fields) and the ``sys_*`` twins of the summary and the
classified contents, which the normaliser also exposes unprefixed. Google
Cloud Run refuses a non-streamed response above 32 MiB, so a Heatmap cell
failed with HTTP 500. The :class:`ResultShape` of a request decides what each
result keeps.
"""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Optional

from pipeline.db import get_metadata_panel_fields

# Document-record keys a search result never carries: whole-record blobs, and
# the ``sys_*`` twin of every heavy field the normaliser exposes unprefixed.
DROPPED_METADATA_KEYS: FrozenSet[str] = frozenset(
    {
        "abstractive_summary",
        "sys_data",
        "sys_full_summary",
        "sys_toc_classified",
        "sys_toc",
        "toc",
        "sys_taxonomies",
        "taxonomies",
        "src_doc_raw_metadata",
    }
)

# Dropped as well in lean mode, for callers that never open a result.
LEAN_DROPPED_METADATA_KEYS: FrozenSet[str] = frozenset(
    {"full_summary", "toc_classified"}
)

# Chunk-level fields a lean result leaves out (set to ``None``).
LEAN_DROPPED_CHUNK_FIELDS: FrozenSet[str] = frozenset(
    {"chunk_elements", "tables", "table_data", "images", "bbox", "elements"}
)


@dataclass(frozen=True)
class ResultShape:
    """What a caller wants on each search result.

    ``lean`` drops the chunk-level element data and the long document texts
    (summary, classified contents) for callers that render a list and never
    open a result, such as a Heatmap cell. ``keep_keys`` are metadata keys the
    caller reads, kept even when they are in :data:`DROPPED_METADATA_KEYS`.
    """

    lean: bool = False
    keep_keys: FrozenSet[str] = frozenset()

    @classmethod
    def for_source(
        cls,
        data_source: Optional[str],
        lean: bool = False,
        keep: Iterable[str] = (),
    ) -> "ResultShape":
        """Shape for ``data_source``: its ``metadata_panel_fields`` are kept."""
        panel_fields = get_metadata_panel_fields(data_source) if data_source else {}
        return cls(lean=lean, keep_keys=frozenset(panel_fields) | frozenset(keep))

    def dropped_metadata_keys(self) -> FrozenSet[str]:
        dropped = DROPPED_METADATA_KEYS - self.keep_keys
        if self.lean:
            dropped |= LEAN_DROPPED_METADATA_KEYS
        return dropped

    def metadata(self, normalized_doc: Dict[str, Any]) -> Dict[str, Any]:
        """The result's ``metadata`` block from a normalised document record."""
        dropped = self.dropped_metadata_keys()
        return {k: v for k, v in normalized_doc.items() if k not in dropped}

    def chunk_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """The chunk-level fields of a result; lean results carry none."""
        if not self.lean:
            return fields
        return {
            k: (None if k in LEAN_DROPPED_CHUNK_FIELDS else v)
            for k, v in fields.items()
        }
