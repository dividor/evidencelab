"""Scanner behaviour on a data refresh.

A refresh re-scans a tree where some documents are unchanged, some have new
metadata and some have new content. These tests pin the three behaviours that
make reuse safe:

  * an existing document point is merged, not replaced, so the document
    embedding, the tagger's ``tag_*`` fields and ``is_duplicate`` survive;
  * a metadata-only change reaches the denormalised chunk payloads;
  * a content change queues the document for re-parsing and drops its stale
    chunks.
"""

import json
from unittest.mock import MagicMock

import pytest

from pipeline.processors.scanning.scanner import ScanProcessor


@pytest.fixture
def scanner(tmp_path):
    processor = ScanProcessor.__new__(ScanProcessor)
    processor.base_dir = str(tmp_path)
    processor.batch_size = 50
    processor.db = MagicMock()
    processor.db.documents_collection = "documents_uneg"
    processor.db.chunks_collection = "chunks_uneg"
    processor.db.delete_document_chunks.return_value = 3
    processor.pg = MagicMock()
    return processor


def write_document(tmp_path, name="report_1.pdf", content=b"pdf bytes", metadata=None):
    folder = tmp_path / "FAO" / "2024"
    folder.mkdir(parents=True, exist_ok=True)
    doc = folder / name
    doc.write_bytes(content)
    meta = {"title": "A report", "agency": "FAO", "year": "2024", "country": "Kenya"}
    meta.update(metadata or {})
    doc.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    return doc


# --- macOS sidecar files ---------------------------------------------------


def test_apple_double_sidecars_are_not_scanned_as_metadata(scanner, tmp_path):
    write_document(tmp_path)
    (tmp_path / "FAO" / "2024" / "._report_1.json").write_bytes(
        b"\x00\x05\x16\x07 apple double"
    )

    found = [p.name for p in scanner._scan_metadata_files()]

    assert found == ["report_1.json"], "ExFAT sidecars must be ignored"


# --- existing points are merged, not replaced ------------------------------


def test_existing_document_payload_is_merged_not_replaced(scanner):
    scanner._flush_batch([("doc-1", {"map_title": "New title"}, True)])

    scanner.db.client.set_payload.assert_called_once()
    kwargs = scanner.db.client.set_payload.call_args.kwargs
    assert kwargs["collection_name"] == "documents_uneg"
    assert kwargs["payload"] == {"map_title": "New title"}
    assert kwargs["points"] == ["doc-1"]
    scanner.db.client.upsert.assert_not_called(), "replacing the point would drop vector and tags"


def test_new_document_is_upserted_as_a_point(scanner):
    scanner._flush_batch([("doc-2", {"map_title": "Brand new"}, False)])

    scanner.db.client.upsert.assert_called_once()
    points = scanner.db.client.upsert.call_args.kwargs["points"]
    assert len(points) == 1 and points[0].id == "doc-2"
    scanner.db.client.set_payload.assert_not_called()


def test_mixed_batch_splits_between_merge_and_upsert(scanner):
    scanner._flush_batch(
        [("old", {"map_title": "t"}, True), ("new", {"map_title": "u"}, False)]
    )

    assert scanner.db.client.set_payload.call_count == 1
    assert len(scanner.db.client.upsert.call_args.kwargs["points"]) == 1


# --- metadata changes reach chunk payloads ---------------------------------


def test_metadata_change_propagates_to_chunk_payloads(scanner):
    scanner._propagate_to_chunks(
        "doc-3",
        {
            "map_country": "Kenya; Uganda",
            "src_theme": "Nutrition",
            "sys_status": "indexed",
        },
    )

    kwargs = scanner.db.client.set_payload.call_args.kwargs
    assert kwargs["collection_name"] == "chunks_uneg"
    assert kwargs["payload"] == {
        "map_country": "Kenya; Uganda",
        "src_theme": "Nutrition",
    }
    condition = kwargs["points"].must[0]
    assert condition.key == "doc_id" and condition.match.value == "doc-3"


def test_propagation_skips_documents_with_no_mapped_fields(scanner):
    scanner._propagate_to_chunks(
        "doc-4", {"sys_status": "indexed", "is_duplicate": False}
    )

    scanner.db.client.set_payload.assert_not_called()


# --- content changes queue a re-parse --------------------------------------


@pytest.mark.parametrize("change_type", ["file", "both"])
def test_content_change_clears_chunks_and_resets_status(scanner, change_type):
    scanner._apply_change_side_effects("doc-5", change_type)

    scanner.db.delete_document_chunks.assert_called_once_with("doc-5")
    fields = scanner.pg.merge_doc_sys_fields.call_args.kwargs["sys_fields"]
    assert fields["sys_status"] == "downloaded", "document must be re-parsed"
    assert fields["sys_parsed_folder"] is None
    assert fields["sys_chunk_count"] == 0


@pytest.mark.parametrize("change_type", ["metadata", "new", "", "status_change"])
def test_non_content_changes_keep_the_processed_output(scanner, change_type):
    scanner._apply_change_side_effects("doc-6", change_type)

    scanner.db.delete_document_chunks.assert_not_called()
    scanner.pg.merge_doc_sys_fields.assert_not_called()


def test_failure_to_delete_chunks_does_not_stop_the_scan(scanner):
    scanner.db.delete_document_chunks.side_effect = RuntimeError("qdrant down")

    scanner._apply_change_side_effects("doc-7", "file")

    # The status reset still happens so the document is not left half-updated.
    assert scanner.pg.merge_doc_sys_fields.called
