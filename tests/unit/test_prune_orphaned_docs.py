"""Tests for pruning orphaned documents.

Two failures this covers, both seen on real data:

* the chunks table has no foreign key to the docs table, so deleting a document
  leaves its chunks behind. The script reported removing 0 chunks while leaving
  84,590 orphaned rows.
* the scan works outward from Postgres, so it cannot see points Qdrant holds
  for documents Postgres never had. Those still answer searches.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "fixes" / "prune_orphaned_docs.py"
)


@pytest.fixture(scope="module")
def prune():
    spec = importlib.util.spec_from_file_location("prune_orphaned_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg():
    client = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 3
    cursor.__enter__ = lambda self: self
    cursor.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = lambda self: self
    conn.__exit__ = lambda self, *a: False
    client._get_conn.return_value = conn
    client._cursor = cursor
    return client


class TestDeleteDocsAndChunks:
    def test_chunks_are_deleted_explicitly_not_left_to_a_cascade(self, prune, pg):
        prune.delete_docs_and_chunks(pg, "docs_uneg", "chunks_uneg", ["a", "b", "c"])

        statements = [call.args[0] for call in pg._cursor.execute.call_args_list]
        assert any(
            s.startswith("DELETE FROM chunks_uneg") for s in statements
        ), "chunks must be deleted explicitly: there is no foreign key to cascade from"
        assert any(s.startswith("DELETE FROM docs_uneg") for s in statements)

    def test_chunks_go_first_so_a_failure_cannot_strand_them(self, prune, pg):
        prune.delete_docs_and_chunks(pg, "docs_uneg", "chunks_uneg", ["a"])

        statements = [call.args[0] for call in pg._cursor.execute.call_args_list]
        chunks_at = next(i for i, s in enumerate(statements) if "chunks_uneg" in s)
        docs_at = next(i for i, s in enumerate(statements) if "docs_uneg" in s)
        assert chunks_at < docs_at

    def test_both_counts_are_reported(self, prune, pg):
        docs, chunks = prune.delete_docs_and_chunks(
            pg, "docs_uneg", "chunks_uneg", ["a"]
        )
        assert docs == 3 and chunks == 3

    def test_deletion_is_batched(self, prune, pg):
        prune.delete_docs_and_chunks(
            pg, "docs_uneg", "chunks_uneg", [str(n) for n in range(25)], batch_size=10
        )
        # three batches, two statements each
        assert pg._cursor.execute.call_count == 6


class TestFindQdrantOrphans:
    @staticmethod
    def _db(pages):
        db = MagicMock()
        db.client.scroll.side_effect = pages
        return db

    def test_document_points_absent_from_postgres_are_found(self, prune):
        points = [
            MagicMock(id="kept", payload=None),
            MagicMock(id="stray", payload=None),
        ]
        db = self._db([(points, None)])

        orphans = prune.find_qdrant_orphans(db, "documents_uneg", {"kept"})

        assert orphans == ["stray"]

    def test_chunk_points_are_matched_by_their_doc_id_payload(self, prune):
        points = [
            MagicMock(id="c1", payload={"doc_id": "kept"}),
            MagicMock(id="c2", payload={"doc_id": "gone"}),
        ]
        db = self._db([(points, None)])

        orphans = prune.find_qdrant_orphans(
            db, "chunks_uneg", {"kept"}, payload_key="doc_id"
        )

        assert orphans == ["c2"]

    def test_every_page_is_scanned(self, prune):
        first = ([MagicMock(id="a", payload=None)], "next")
        second = ([MagicMock(id="b", payload=None)], None)
        db = self._db([first, second])

        assert prune.find_qdrant_orphans(db, "documents_uneg", set()) == ["a", "b"]

    def test_a_chunk_with_no_payload_counts_as_orphaned(self, prune):
        points = [MagicMock(id="c1", payload=None)]
        db = self._db([(points, None)])

        assert prune.find_qdrant_orphans(
            db, "chunks_uneg", {"kept"}, payload_key="doc_id"
        ) == ["c1"]

    def test_nothing_is_flagged_when_every_point_is_known(self, prune):
        points = [MagicMock(id="c1", payload={"doc_id": "kept"})]
        db = self._db([(points, None)])

        assert (
            prune.find_qdrant_orphans(db, "chunks_uneg", {"kept"}, payload_key="doc_id")
            == []
        )
