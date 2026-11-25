"""Tests for scripts/sync/db/load_dump_from_s3.py: loading a dump into a deployment."""

import hashlib
import io
import json
from unittest.mock import MagicMock, patch

import pytest

import scripts.sync.db.load_dump_from_s3 as ld

pytestmark = pytest.mark.unit

# What the container gets from Secrets Manager; any text will do here.
FAKE_QDRANT_KEY = "from-secrets-manager"

ENV = {
    "TRANSFER_BUCKET": "evidencelab-transfer-1",
    "QDRANT_HOST": "http://10.0.0.5:6333/",
    "QDRANT_API_KEY": FAKE_QDRANT_KEY,
}
STAMP = "20261121T043910Z"
PREFIX = f"dumps/{STAMP}"
FILES = {
    f"{PREFIX}/postgres-evidencelab-{STAMP}.sql.gz": b"sql" * 50,
    f"{PREFIX}/qdrant-chunks_wfp-{STAMP}.snapshot": b"chunks" * 70,
    f"{PREFIX}/qdrant-documents_wfp-{STAMP}.snapshot": b"documents" * 9,
    f"{PREFIX}/wfp-{STAMP}.tar": b"tar" * 300,
}


def _manifest(files=None, **fields):
    manifest = {
        "created": STAMP,
        "database": "evidencelab",
        "data_source": "wfp",
        "qdrant": "1.18.3",
        "files": [
            {"key": key, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for key, body in (FILES if files is None else files).items()
        ],
    }
    manifest.update(fields)
    return manifest


class FakeS3:
    """The transfer bucket, holding OBJECTS."""

    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        assert Bucket == ENV["TRANSFER_BUCKET"]
        return {"Body": io.BytesIO(self.objects[Key])}

    def generate_presigned_url(self, method, Params, ExpiresIn):
        assert method == "get_object" and ExpiresIn == 3600
        return f"https://{Params['Bucket']}.s3.amazonaws.com/{Params['Key']}?signed"


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _qdrant(version="1.18.4", recover_status=200, counts=None):
    """A Qdrant server of VERSION whose collections hold COUNTS points."""
    counts = counts or {"chunks_wfp": 1200, "documents_wfp": 30}
    http = MagicMock()
    http.get.return_value = FakeResponse(body={"version": version})
    http.put.return_value = FakeResponse(status=recover_status, body={"result": True})
    http.post.side_effect = lambda url, **_: FakeResponse(
        body={"result": {"count": counts[url.split("/")[-3]]}}
    )
    return http


class TestReadManifest:
    def test_read_manifest_when_complete_then_returns_it(self):
        s3 = FakeS3({f"{PREFIX}/manifest.json": json.dumps(_manifest()).encode()})

        manifest = ld.read_manifest(
            s3, ENV["TRANSFER_BUCKET"], f"{PREFIX}/manifest.json"
        )

        assert manifest["created"] == STAMP
        assert len(manifest["files"]) == 4

    @pytest.mark.parametrize("field", ["created", "data_source", "qdrant", "files"])
    def test_read_manifest_when_field_missing_then_refuses(self, field):
        manifest = _manifest()
        del manifest[field]
        s3 = FakeS3({"m.json": json.dumps(manifest).encode()})

        with pytest.raises(ValueError, match=field):
            ld.read_manifest(s3, ENV["TRANSFER_BUCKET"], "m.json")


class TestCheckFiles:
    def test_check_files_when_all_match_then_reports_each(self, capsys):
        ld.check_files(FakeS3(FILES), ENV["TRANSFER_BUCKET"], _manifest())

        out = capsys.readouterr().out
        assert out.count("sha256 matches") == 4

    def test_check_files_when_content_differs_then_refuses(self):
        objects = dict(FILES)
        objects[f"{PREFIX}/wfp-{STAMP}.tar"] = b"TAR" * 300  # same size, other bytes

        with pytest.raises(ValueError, match=f"wfp-{STAMP}.tar"):
            ld.check_files(FakeS3(objects), ENV["TRANSFER_BUCKET"], _manifest())

    def test_check_files_when_file_shorter_then_refuses(self):
        objects = dict(FILES)
        objects[f"{PREFIX}/qdrant-chunks_wfp-{STAMP}.snapshot"] = b"chunks"

        with pytest.raises(ValueError, match="6 bytes"):
            ld.check_files(FakeS3(objects), ENV["TRANSFER_BUCKET"], _manifest())


class TestRestoreArgs:
    def test_restore_args_when_dump_complete_then_names_export_and_archive(self):
        args = ld.restore_args(_manifest(), "evidencelab")

        assert args.postgres_key == f"{PREFIX}/postgres-evidencelab-{STAMP}.sql.gz"
        assert args.data_key == f"{PREFIX}/wfp-{STAMP}.tar"
        assert args.data_source == "wfp"
        assert args.database == "evidencelab"

    def test_restore_args_when_archive_missing_then_refuses(self):
        files = {k: v for k, v in FILES.items() if not k.endswith(".tar")}

        with pytest.raises(ValueError, match=f"wfp-{STAMP}.tar"):
            ld.restore_args(_manifest(files), "evidencelab")

    def test_restore_args_when_two_exports_then_refuses(self):
        files = dict(FILES)
        files[f"{PREFIX}/postgres-other-{STAMP}.sql.gz"] = b"other"

        with pytest.raises(ValueError, match="one postgres"):
            ld.restore_args(_manifest(files), "evidencelab")


class TestSnapshotEntries:
    def test_snapshot_entries_when_dump_has_two_then_names_their_collections(self):
        names = [name for name, _ in ld.snapshot_entries(_manifest())]

        assert names == ["chunks_wfp", "documents_wfp"]

    def test_snapshot_entries_when_none_then_refuses(self):
        files = {k: v for k, v in FILES.items() if not k.endswith(".snapshot")}

        with pytest.raises(ValueError, match="no Qdrant snapshots"):
            ld.snapshot_entries(_manifest(files))

    def test_snapshot_entries_when_name_not_plain_then_refuses(self):
        files = {f"{PREFIX}/qdrant-Chunks-WFP-{STAMP}.snapshot": b"x"}

        with pytest.raises(ValueError, match="not a plain"):
            ld.snapshot_entries(_manifest(files))


@pytest.mark.parametrize(
    "dumped, running, same",
    [
        ("1.18.3", "1.18.3", True),
        ("1.18.3", "1.18.9", True),
        ("1.18.3", "1.19.0", False),
    ],
)
def test_same_minor_when_compared_then_matches_major_and_minor(dumped, running, same):
    assert ld.same_minor(dumped, running) is same


class TestLoadSnapshots:
    def test_load_snapshots_when_same_minor_then_recovers_each_with_checksum(
        self, capsys
    ):
        http = _qdrant()
        manifest = _manifest()

        counts = ld.load_snapshots(manifest, ENV, FakeS3(FILES), http)

        assert counts == {"chunks_wfp": 1200, "documents_wfp": 30}
        sums = {e["key"]: e["sha256"] for e in manifest["files"]}
        calls = http.put.call_args_list
        assert [c.args[0] for c in calls] == [
            "http://10.0.0.5:6333/collections/chunks_wfp/snapshots/recover",
            "http://10.0.0.5:6333/collections/documents_wfp/snapshots/recover",
        ]
        chunks = calls[0].kwargs
        key = f"{PREFIX}/qdrant-chunks_wfp-{STAMP}.snapshot"
        assert chunks["json"] == {
            "location": f"https://evidencelab-transfer-1.s3.amazonaws.com/{key}?signed",
            "priority": "snapshot",
            "checksum": sums[key],
        }
        assert chunks["params"] == {"wait": "true"}
        assert chunks["headers"] == {"api-key": FAKE_QDRANT_KEY}
        assert http.post.call_args.kwargs["json"] == {"exact": True}
        assert "Loaded chunks_wfp" in capsys.readouterr().out

    def test_load_snapshots_when_other_minor_then_refuses_before_loading(self):
        http = _qdrant(version="1.19.0")

        with pytest.raises(ValueError, match="1.18.3.*1.19.0"):
            ld.load_snapshots(_manifest(), ENV, FakeS3(FILES), http)
        http.put.assert_not_called()

    def test_load_snapshots_when_qdrant_refuses_then_raises(self):
        http = _qdrant(recover_status=400)

        with pytest.raises(RuntimeError, match="recover chunks_wfp"):
            ld.load_snapshots(_manifest(), ENV, FakeS3(FILES), http)


class TestMain:
    def _s3(self, manifest):
        objects = dict(FILES)
        objects[f"{PREFIX}/manifest.json"] = json.dumps(manifest).encode()
        return FakeS3(objects)

    def test_main_when_check_then_checks_files(self, capsys):
        with patch("boto3.client", return_value=self._s3(_manifest())):
            code = ld.main(["check", "--manifest", f"{PREFIX}/manifest.json"], ENV)

        assert code == 0
        assert capsys.readouterr().out.count("sha256 matches") == 4

    def test_main_when_restore_then_restores_export_and_archive(self):
        with patch("boto3.client", return_value=self._s3(_manifest())), patch.object(
            ld, "restore"
        ) as restore:
            code = ld.main(
                [
                    "restore",
                    "--manifest",
                    f"{PREFIX}/manifest.json",
                    "--database",
                    "evidencelab",
                ],
                ENV,
            )

        assert code == 0
        args, env = restore.call_args.args
        assert args.data_key == f"{PREFIX}/wfp-{STAMP}.tar"
        assert env == ENV

    def test_main_when_snapshots_then_loads_them(self):
        with patch("boto3.client", return_value=self._s3(_manifest())), patch.object(
            ld, "load_snapshots"
        ) as load:
            code = ld.main(["snapshots", "--manifest", f"{PREFIX}/manifest.json"], ENV)

        assert code == 0
        assert load.call_args.args[0]["created"] == STAMP

    def test_main_when_file_differs_then_exits_1_with_reason(self, capsys):
        manifest = _manifest()
        manifest["files"][0]["sha256"] = "0" * 64

        with patch("boto3.client", return_value=self._s3(manifest)):
            code = ld.main(["check", "--manifest", f"{PREFIX}/manifest.json"], ENV)

        assert code == 1
        assert "error:" in capsys.readouterr().err

    def test_main_when_started_then_signs_links_with_version_4(self):
        with patch("boto3.client", return_value=self._s3(_manifest())) as client:
            ld.main(["check", "--manifest", f"{PREFIX}/manifest.json"], ENV)

        assert client.call_args.kwargs["config"].signature_version == "s3v4"


class FakeTarget:
    """This deployment's transfer bucket, recording what is written to it."""

    def __init__(self):
        self.uploaded = {}
        self.put = {}

    def upload_file(self, filename, bucket, key):
        assert bucket == ENV["TRANSFER_BUCKET"]
        with open(filename, "rb") as f:
            self.uploaded[key] = f.read()

    def put_object(self, Bucket, Key, Body):
        self.put[Key] = Body


class FakeDownload:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self._content = content

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


def _links(manifest=None):
    manifest = manifest or _manifest()
    return {
        "manifest": manifest,
        "links": {
            e["key"]: f"https://source/{e['key']}?signed" for e in manifest["files"]
        },
    }


def _source(files=None, status=200):
    """The other account's bucket, reached through its signed links."""
    files = FILES if files is None else files
    http = MagicMock()
    http.get.side_effect = lambda url, **_: FakeDownload(
        status, files[url.removeprefix("https://source/").removesuffix("?signed")]
    )
    return http


class TestFetchDump:
    def test_fetch_dump_when_files_match_then_uploads_each_and_manifest_last(
        self, tmp_path
    ):
        target = FakeTarget()

        key = ld.fetch_dump(
            _links(), ENV["TRANSFER_BUCKET"], target, _source(), tmp_path
        )

        assert key == f"{PREFIX}/manifest.json"
        assert target.uploaded == FILES
        assert json.loads(target.put[key]) == _manifest()
        assert list(tmp_path.iterdir()) == []

    def test_fetch_dump_when_download_differs_then_uploads_nothing_of_it(
        self, tmp_path
    ):
        files = dict(FILES)
        files[f"{PREFIX}/wfp-{STAMP}.tar"] = b"TAR" * 300
        target = FakeTarget()

        with pytest.raises(ValueError, match=f"wfp-{STAMP}.tar"):
            ld.fetch_dump(
                _links(), ENV["TRANSFER_BUCKET"], target, _source(files), tmp_path
            )
        assert f"{PREFIX}/wfp-{STAMP}.tar" not in target.uploaded
        assert target.put == {}

    def test_fetch_dump_when_link_refused_then_raises_without_the_link(self, tmp_path):
        with pytest.raises(RuntimeError) as raised:
            ld.fetch_dump(
                _links(),
                ENV["TRANSFER_BUCKET"],
                FakeTarget(),
                _source(status=403),
                tmp_path,
            )
        assert "HTTP 403" in str(raised.value)
        assert "signed" not in str(raised.value)

    def test_fetch_dump_when_link_missing_then_refuses_before_downloading(
        self, tmp_path
    ):
        links = _links()
        del links["links"][f"{PREFIX}/wfp-{STAMP}.tar"]
        http = _source()

        with pytest.raises(ValueError, match="no link"):
            ld.fetch_dump(links, ENV["TRANSFER_BUCKET"], FakeTarget(), http, tmp_path)
        http.get.assert_not_called()

    @pytest.mark.parametrize(
        "keys",
        [
            ["uploads/x/a.tar"],
            ["dumps/a/x.tar", "dumps/b/y.tar"],
            ["dumps/a/../../x.tar"],
        ],
    )
    def test_dump_folder_when_not_one_folder_under_dumps_then_refuses(self, keys):
        manifest = _manifest({k: b"x" for k in keys})

        with pytest.raises(ValueError, match="one folder under dumps/"):
            ld.dump_folder(manifest)

    def test_main_when_fetch_then_reads_links_and_copies(self, tmp_path):
        links_key = f"{PREFIX}/links.json"
        bucket = FakeS3({links_key: json.dumps(_links()).encode()})
        bucket.upload_file = MagicMock()
        bucket.put_object = MagicMock()

        with patch("boto3.client", return_value=bucket), patch(
            "requests.get", side_effect=_source().get.side_effect
        ), patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            code = ld.main(["fetch", "--links", links_key], ENV)

        assert code == 0
        assert bucket.upload_file.call_count == 4
        assert bucket.put_object.call_args.kwargs["Key"] == f"{PREFIX}/manifest.json"
