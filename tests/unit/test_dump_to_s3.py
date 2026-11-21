"""Tests for scripts/sync/db/dump_to_s3.py: dumping the database, Qdrant and the data folder."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.sync.db.dump_to_s3 as ds
import scripts.sync.db.restore_from_s3 as rs

pytestmark = pytest.mark.unit

# What the container gets from Secrets Manager; any text will do here.
FAKE_DB_LOGIN = "from-secrets-manager"
FAKE_QDRANT_KEY = "from-secrets-manager-too"

ENV = {
    "POSTGRES_HOST": "db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "evidencelab",
    "POSTGRES_PASSWORD": FAKE_DB_LOGIN,
    "POSTGRES_DB": "evidencelab",
    "PGSSLMODE": "verify-full",
    "TRANSFER_BUCKET": "evidencelab-transfer-1",
    "QDRANT_HOST": "http://10.0.0.5:6333",
    "QDRANT_API_KEY": FAKE_QDRANT_KEY,
}
SQL = b"CREATE TABLE public.docs_wfp (id integer);\nCOPY public.docs_wfp (id) FROM stdin;\n1\n\\.\n"
SNAPSHOT = b"qdrant snapshot bytes" * 100
NOW = 1795230300.0  # 2026-11-21 03:05:00 UTC


class FakeResponse:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body or {}
        self._content = content
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


def _http(download_status=200):
    http = MagicMock()
    http.post.side_effect = lambda url, **_: FakeResponse(
        body={"result": {"name": f"{url.split('/')[-2]}-1.snapshot"}}
    )

    def get(url, **_):
        if url.endswith("/"):
            return FakeResponse(body={"version": "1.18.3"})
        return FakeResponse(status=download_status, content=SNAPSHOT)

    http.get.side_effect = get
    http.delete.return_value = FakeResponse()
    return http


def _pg_dump(returncode=0):
    process = MagicMock()
    process.stdout = io.BytesIO(SQL)
    process.wait.return_value = returncode
    process.returncode = returncode
    return process


def _data_folder(root: Path) -> Path:
    """A data source folder as the pipeline leaves it: a PDF and a parsed folder linking to it."""
    pdf = root / "wfp" / "pdfs" / "WFP" / "2018" / "report.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.7 report")
    parsed = root / "wfp" / "parsed" / "WFP" / "2018" / "report"
    parsed.mkdir(parents=True)
    (parsed / "report.md").write_text("# Report\n")
    os.symlink("../../../../pdfs/WFP/2018/report.pdf", parsed / "report.pdf")
    return root


def _args(**overrides):
    values = {"data_source": "wfp", "database": "evidencelab", "prefix": "dumps"}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_dump_stamp_is_utc_and_sortable():
    assert ds.dump_stamp(NOW) == "20261121T030500Z"


def test_pg_dump_command_leaves_out_ownership_and_privileges():
    command = ds.pg_dump_command("evidencelab")
    assert command[0] == "pg_dump"
    assert {"--format=plain", "--no-owner", "--no-privileges"} <= set(command)
    assert command[-2:] == ["-d", "evidencelab"]


def test_dump_postgres_when_pg_dump_succeeds_then_gzipped_sql_is_written(tmp_path):
    path = tmp_path / "db.sql.gz"
    with patch.object(ds.subprocess, "Popen", return_value=_pg_dump()) as popen:
        ds.dump_postgres(ENV, "evidencelab", path)

    assert gzip.decompress(path.read_bytes()) == SQL
    env = popen.call_args.kwargs["env"]
    assert env["PGHOST"] == "db.internal" and env["PGSSLMODE"] == "verify-full"


def test_dump_postgres_when_pg_dump_fails_then_it_raises(tmp_path):
    with patch.object(ds.subprocess, "Popen", return_value=_pg_dump(returncode=1)):
        with pytest.raises(RuntimeError, match="pg_dump stopped with exit code 1"):
            ds.dump_postgres(ENV, "evidencelab", tmp_path / "db.sql.gz")


def test_qdrant_snapshot_when_taken_then_downloaded_and_removed_from_qdrant(tmp_path):
    http = _http()
    path = tmp_path / "chunks.snapshot"

    ds.qdrant_snapshot(
        "http://10.0.0.5:6333/", FAKE_QDRANT_KEY, "chunks_wfp", path, http
    )

    assert path.read_bytes() == SNAPSHOT
    url = "http://10.0.0.5:6333/collections/chunks_wfp/snapshots"
    assert http.post.call_args.args[0] == url
    assert http.delete.call_args.args[0] == f"{url}/chunks_wfp-1.snapshot"
    assert http.post.call_args.kwargs["headers"] == {"api-key": FAKE_QDRANT_KEY}


def test_qdrant_snapshot_when_download_fails_then_removed_and_it_raises(tmp_path):
    http = _http(download_status=500)

    with pytest.raises(RuntimeError, match="send the snapshot of chunks_wfp"):
        ds.qdrant_snapshot(
            "http://q:6333", FAKE_QDRANT_KEY, "chunks_wfp", tmp_path / "s", http
        )

    http.delete.assert_called_once()


def test_archive_folder_when_restored_then_files_and_links_come_back(tmp_path):
    source = _data_folder(tmp_path / "source")
    archive = tmp_path / "wfp.tar"

    ds.archive_folder(str(source), "wfp", archive)
    with open(archive, "rb") as stream:
        counts = rs.extract_archive(stream, "wfp", root=str(tmp_path / "target"))

    restored = tmp_path / "target" / "wfp"
    assert counts.files == 2
    assert (restored / "pdfs/WFP/2018/report.pdf").read_bytes() == b"%PDF-1.7 report"
    link = restored / "parsed/WFP/2018/report/report.pdf"
    assert link.is_symlink() and link.read_bytes() == b"%PDF-1.7 report"


def test_archive_folder_when_folder_missing_then_it_raises(tmp_path):
    with pytest.raises(ValueError, match="is not a folder"):
        ds.archive_folder(str(tmp_path), "wfp", tmp_path / "wfp.tar")


def test_dump_when_database_does_not_match_then_nothing_is_written(tmp_path):
    s3 = MagicMock()
    with patch.object(ds, "configured_folders", return_value=["wfp"]):
        with pytest.raises(ValueError, match="does not match"):
            ds.dump(
                _args(database="other"),
                ENV,
                s3,
                _http(),
                work=tmp_path,
                now=lambda: NOW,
            )
    s3.upload_file.assert_not_called()


def test_dump_when_data_source_unknown_then_nothing_is_written(tmp_path):
    s3 = MagicMock()
    with patch.object(ds, "configured_folders", return_value=["uneg"]):
        with pytest.raises(ValueError, match="not a data source"):
            ds.dump(_args(), ENV, s3, _http(), work=tmp_path, now=lambda: NOW)
    s3.upload_file.assert_not_called()


def test_dump_writes_every_file_and_a_manifest_of_their_checksums(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(ds, "DATA_ROOT", str(_data_folder(tmp_path / "data")))
    work = tmp_path / "work"
    work.mkdir()
    uploaded = {}
    s3 = MagicMock()
    s3.upload_file.side_effect = lambda path, bucket, key: uploaded.__setitem__(
        key, hashlib.sha256(Path(path).read_bytes()).hexdigest()
    )
    versions = MagicMock(
        side_effect=[MagicMock(stdout="17.9\n"), MagicMock(stdout="pg_dump 17.6\n")]
    )

    with patch.object(ds, "configured_folders", return_value=["wfp"]), patch.object(
        ds.subprocess, "Popen", return_value=_pg_dump()
    ), patch.object(ds.subprocess, "run", versions):
        files = ds.dump(_args(), ENV, s3, _http(), work=work, now=lambda: NOW)

    prefix = "dumps/20261121T030500Z"
    assert [f.key for f in files] == [
        f"{prefix}/postgres-evidencelab-20261121T030500Z.sql.gz",
        f"{prefix}/qdrant-chunks_wfp-20261121T030500Z.snapshot",
        f"{prefix}/qdrant-documents_wfp-20261121T030500Z.snapshot",
        f"{prefix}/wfp-20261121T030500Z.tar",
    ]
    assert {f.key: f.sha256 for f in files} == uploaded
    assert list(work.iterdir()) == []
    manifest_call = s3.put_object.call_args.kwargs
    assert manifest_call["Key"] == f"{prefix}/manifest.json"
    manifest = json.loads(manifest_call["Body"])
    assert manifest["postgres_server"] == "17.9" and manifest["qdrant"] == "1.18.3"
    assert [f["sha256"] for f in manifest["files"]] == [f.sha256 for f in files]
