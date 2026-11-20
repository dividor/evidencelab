"""Tests for scripts/sync/db/restore_from_s3.py (cloud restore of an export and a data archive)."""

import argparse
import gzip
import io
import os
import tarfile
from unittest.mock import MagicMock, call, patch

import pytest

import scripts.sync.db.restore_from_s3 as rs

pytestmark = pytest.mark.unit

EXPORT = [
    "SET statement_timeout = 0;\n",
    "SELECT pg_catalog.set_config('search_path', '', false);\n",
    "\\restrict abc123\n",
    "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;\n",
    "CREATE TABLE public.docs_wfp (id integer, title text);\n",
    "ALTER TABLE public.docs_wfp OWNER TO cloudsqlsuperuser;\n",
    "COPY public.docs_wfp (id, title) FROM stdin;\n",
    "1\tGRANT ALL ON docs_wfp TO someone;\n",
    "2\tALTER TABLE x OWNER TO y;\n",
    "\\.\n",
    "GRANT SELECT ON TABLE public.docs_wfp TO PUBLIC;\n",
    'REVOKE ALL ON SCHEMA public FROM "evl-admin";\n',
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres GRANT ALL ON TABLES TO evidencelab;\n",
    "\\unrestrict abc123\n",
]

# What the container gets from Secrets Manager; any text will do here.
FAKE_DB_LOGIN = "from-secrets-manager"

ENV = {
    "POSTGRES_HOST": "db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "evidencelab",
    "POSTGRES_PASSWORD": FAKE_DB_LOGIN,
    "POSTGRES_DB": "evidencelab",
    "PGSSLMODE": "verify-full",
    "TRANSFER_BUCKET": "evidencelab-transfer-1",
}


def _tar(members, mode="w:gz"):
    """An in-memory tar holding MEMBERS.

    Each is (name, bytes) for a file, (name, None) for a folder, or
    (name, "-> target") for a symbolic link.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif isinstance(data, str):
                info.type = tarfile.SYMTYPE
                info.linkname = data.removeprefix("-> ")
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    return buffer


class TestWithoutPrivileges:
    def test_without_privileges_when_export_then_ownership_and_grants_left_out(self):
        summary = rs.ExportSummary()
        kept = list(rs.without_privileges(EXPORT, summary))
        assert not any(
            line.startswith(("ALTER TABLE public", "GRANT", "REVOKE", "ALTER DEFAULT"))
            for line in kept
        )
        assert summary.left_out == 4

    def test_without_privileges_when_table_data_looks_like_grants_then_kept(self):
        kept = list(rs.without_privileges(EXPORT, rs.ExportSummary()))
        assert "1\tGRANT ALL ON docs_wfp TO someone;\n" in kept
        assert "2\tALTER TABLE x OWNER TO y;\n" in kept

    def test_without_privileges_when_export_then_everything_else_passes_unchanged(self):
        kept = list(rs.without_privileges(EXPORT, rs.ExportSummary()))
        left_out = {EXPORT[5], EXPORT[10], EXPORT[11], EXPORT[12]}
        assert kept == [line for line in EXPORT if line not in left_out]

    def test_without_privileges_when_export_then_summary_counts_it(self):
        summary = rs.ExportSummary()
        list(rs.without_privileges(EXPORT, summary))
        assert summary.lines == len(EXPORT)
        assert summary.rows == {"public.docs_wfp": 2}
        assert summary.extensions == ["vector"]
        assert summary.roles == {
            "cloudsqlsuperuser": 1,
            "PUBLIC": 1,
            "evl-admin": 1,
            "evidencelab": 1,
        }
        assert summary.settings == [EXPORT[0].strip(), EXPORT[1].strip()]


class TestExportLines:
    def test_export_lines_when_gz_key_then_gunzipped(self):
        stream = io.BytesIO(gzip.compress("".join(EXPORT).encode()))
        assert list(rs.export_lines(stream, "postgres.sql.gz")) == EXPORT

    def test_export_lines_when_plain_key_then_read_as_is(self):
        stream = io.BytesIO("".join(EXPORT).encode())
        assert list(rs.export_lines(stream, "postgres.sql")) == EXPORT

    def test_export_lines_when_crlf_then_line_endings_kept(self):
        stream = io.BytesIO(b"SELECT 1;\r\nSELECT 2;\r\n")
        assert list(rs.export_lines(stream, "x.sql")) == [
            "SELECT 1;\r\n",
            "SELECT 2;\r\n",
        ]


class TestInspect:
    def test_print_summary_when_export_then_lists_what_it_holds(self, capsys):
        rs.print_summary(rs.inspect_export(EXPORT))
        out = capsys.readouterr().out
        assert "Extensions: vector" in out
        assert "Ownership and privilege statements left out: 4" in out
        assert "cloudsqlsuperuser (1)" in out
        assert "public.docs_wfp: 2 rows" in out


class TestExtractArchive:
    def test_extract_archive_when_folder_then_files_unpacked(self, tmp_path):
        archive = _tar(
            [("wfp", None), ("wfp/pdfs/a.pdf", b"%PDF"), ("wfp/parsed/a/a.json", b"{}")]
        )
        assert rs.extract_archive(archive, "wfp", str(tmp_path)).files == 2
        assert (tmp_path / "wfp/pdfs/a.pdf").read_bytes() == b"%PDF"
        assert (tmp_path / "wfp/parsed/a/a.json").read_bytes() == b"{}"

    def test_extract_archive_when_dot_slash_names_then_accepted(self, tmp_path):
        archive = _tar([("./wfp/pdfs/a.pdf", b"%PDF")])
        assert rs.extract_archive(archive, "wfp", str(tmp_path)).files == 1

    def test_extract_archive_when_plain_tar_then_read_too(self, tmp_path):
        archive = _tar([("./wfp/pdfs/a.pdf", b"%PDF")], mode="w")
        assert rs.extract_archive(archive, "wfp", str(tmp_path)).files == 1

    def test_extract_archive_when_other_folder_then_refused(self, tmp_path):
        archive = _tar([("wfp/a.pdf", b"x"), ("uneg/b.pdf", b"y")])
        with pytest.raises(ValueError, match="'uneg/b.pdf', outside wfp/"):
            rs.extract_archive(archive, "wfp", str(tmp_path))
        assert not (tmp_path / "uneg").exists()

    def test_extract_archive_when_prefix_only_looks_alike_then_refused(self, tmp_path):
        with pytest.raises(ValueError, match="outside wfp/"):
            rs.extract_archive(_tar([("wfp2/a.pdf", b"x")]), "wfp", str(tmp_path))

    def test_extract_archive_when_path_leaves_root_then_refused(self, tmp_path):
        root = tmp_path / "data"
        root.mkdir()
        with pytest.raises(tarfile.OutsideDestinationError):
            rs.extract_archive(
                _tar([("wfp/../../escaped.txt", b"x")]), "wfp", str(root)
            )
        assert not (tmp_path / "escaped.txt").exists()


PDF = "WFP/2023/report_789.pdf"
PARSED_LINK = "./wfp/parsed/WFP/2023/report_789/report_789.pdf"


class TestPortableLinks:
    @pytest.mark.parametrize(
        "target",
        [
            "/mnt/data/pipeline/wfp/pdfs/" + PDF,  # pipeline run on the host
            "/app/data/wfp/pdfs/" + PDF,  # pipeline run in a container
        ],
    )
    def test_extract_archive_when_absolute_link_into_folder_then_points_at_same_file(
        self, tmp_path, target
    ):
        archive = _tar([("./wfp/pdfs/" + PDF, b"%PDF"), (PARSED_LINK, "-> " + target)])
        counts = rs.extract_archive(archive, "wfp", str(tmp_path))
        link = tmp_path / PARSED_LINK
        assert counts.links_rewritten == 1
        assert os.readlink(link) == "../../../../pdfs/" + PDF
        assert link.read_bytes() == b"%PDF"

    def test_extract_archive_when_relative_link_inside_then_kept(self, tmp_path):
        archive = _tar(
            [("wfp/pdfs/a.pdf", b"%PDF"), ("wfp/parsed/a/a.pdf", "-> ../../pdfs/a.pdf")]
        )
        counts = rs.extract_archive(archive, "wfp", str(tmp_path))
        assert counts.links_rewritten == 0
        assert (tmp_path / "wfp/parsed/a/a.pdf").read_bytes() == b"%PDF"

    @pytest.mark.parametrize(
        "target",
        ["/etc/passwd", "/home/wfp/data/wfp/pdfs/a.pdf", "/data/wfp/../../etc/passwd"],
    )
    def test_extract_archive_when_absolute_link_elsewhere_then_refused(
        self, tmp_path, target
    ):
        archive = _tar([("wfp/parsed/a/a.pdf", "-> " + target)])
        with pytest.raises(ValueError, match="not a file inside one wfp/ folder"):
            rs.extract_archive(archive, "wfp", str(tmp_path))
        assert not (tmp_path / "wfp/parsed/a/a.pdf").is_symlink()

    def test_portable_link_target_when_host_path_then_relative_to_member(self):
        assert (
            rs.portable_link_target(
                PARSED_LINK, "/mnt/data/pipeline/wfp/pdfs/" + PDF, "wfp"
            )
            == "../../../../pdfs/" + PDF
        )


class TestNamesAndCommands:
    @pytest.mark.parametrize("name", ["evidencelab", "evidencelab_restore", "_x1"])
    def test_checked_name_when_plain_then_returned(self, name):
        assert rs.checked_name(name, "db") == name

    @pytest.mark.parametrize("name", ["Evidencelab", 'x"; drop', "a-b", "", "1db"])
    def test_checked_name_when_not_plain_then_refused(self, name):
        with pytest.raises(ValueError, match="not a plain database name"):
            rs.checked_name(name, "db")

    def test_psql_command_when_variables_then_passed_as_psql_variables(self):
        command = rs.psql_command(
            "postgres", {"database": "evidencelab"}, one_transaction=True
        )
        assert command == [
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            "postgres",
            "--single-transaction",
            "-v",
            "database=evidencelab",
        ]

    def test_psql_environment_when_container_settings_then_psql_settings(self):
        env = rs.psql_environment(ENV)
        assert (env["PGHOST"], env["PGPORT"], env["PGUSER"]) == (
            "db.internal",
            "5432",
            "evidencelab",
        )
        assert env["PGPASSWORD"] == FAKE_DB_LOGIN
        assert env["PGSSLMODE"] == "verify-full"

    def test_admin_scripts_when_read_then_names_only_as_psql_variables(self):
        for script in (rs._RECREATE_RESTORE_DB, rs._CLOSE_RUNNING_DB, rs._SWAP):
            assert "evidencelab" not in script
        assert ':"database" RENAME TO :"previous"' in rs._SWAP
        assert ':"restore" RENAME TO :"database"' in rs._SWAP


class _FakePsql:
    def __init__(self, returncode=0, broken_after=None):
        self.written = []
        self.returncode = returncode
        self._broken_after = broken_after
        self.stdin = MagicMock()
        self.stdin.write.side_effect = self._write

    def _write(self, line):
        if self._broken_after is not None and len(self.written) >= self._broken_after:
            raise BrokenPipeError
        self.written.append(line)

    def wait(self):
        return self.returncode


class TestRunPsql:
    def test_run_psql_when_psql_succeeds_then_every_line_written(self):
        fake = _FakePsql()
        with patch.object(rs.subprocess, "Popen", return_value=fake) as popen:
            rs.run_psql(
                ["a\n", "b\n"], ENV, "evidencelab_restore", one_transaction=True
            )
        assert fake.written == ["a\n", "b\n"]
        assert "--single-transaction" in popen.call_args.args[0]
        assert popen.call_args.kwargs["env"]["PGPASSWORD"] == FAKE_DB_LOGIN

    def test_run_psql_when_psql_fails_then_raises(self):
        with patch.object(rs.subprocess, "Popen", return_value=_FakePsql(returncode=3)):
            with pytest.raises(RuntimeError, match="exit code 3"):
                rs.run_psql(["bad\n"], ENV, "x")

    def test_run_psql_when_psql_stops_reading_then_its_error_is_raised(self):
        fake = _FakePsql(returncode=3, broken_after=1)
        with patch.object(rs.subprocess, "Popen", return_value=fake):
            with pytest.raises(RuntimeError, match="exit code 3"):
                rs.run_psql(["a\n", "b\n", "c\n"], ENV, "x")
        assert fake.written == ["a\n"]


def _args(**overrides):
    values = {
        "postgres_key": "pg.sql.gz",
        "data_key": "wfp.tar.gz",
        "data_source": "wfp",
        "database": "evidencelab",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestRestore:
    def _run(self, args):
        calls = MagicMock()
        with patch.object(
            rs, "configured_folders", return_value=["wfp", "uneg"]
        ), patch.object(
            rs,
            "s3_stream",
            side_effect=lambda bucket, key: io.BytesIO(gzip.compress(b"SELECT 1;\n")),
        ) as s3, patch.object(
            rs,
            "extract_archive",
            side_effect=lambda *a: calls.extract(*a) or rs.ArchiveCounts(files=7),
        ), patch.object(
            rs,
            "run_psql",
            side_effect=lambda lines, env, db, *a, **k: calls.psql(
                list(lines), db, *a, **k
            ),
        ):
            rs.restore(args, ENV)
        return calls, s3

    def test_restore_when_args_right_then_files_load_close_and_swap_in_order(self):
        calls, s3 = self._run(_args())
        names = calls.psql.call_args_list[0].args[2]
        assert (
            names["database"] == "evidencelab"
            and names["restore"] == "evidencelab_restore"
        )
        assert names["previous"].startswith("evidencelab_before_")
        assert [c.args[1] for c in calls.psql.call_args_list] == [
            "postgres",
            "evidencelab_restore",
            "postgres",
            "postgres",
        ]
        assert calls.psql.call_args_list[0].args[0] == [rs._RECREATE_RESTORE_DB]
        assert calls.psql.call_args_list[1].args[0] == ["SELECT 1;\n"]
        assert calls.psql.call_args_list[1].kwargs == {"one_transaction": True}
        assert calls.psql.call_args_list[2].args[0] == [rs._CLOSE_RUNNING_DB]
        assert calls.psql.call_args_list[3].args[0] == [rs._SWAP]
        assert calls.psql.call_args_list[3].kwargs == {"one_transaction": True}
        assert s3.call_args_list == [
            call("evidencelab-transfer-1", "wfp.tar.gz"),
            call("evidencelab-transfer-1", "pg.sql.gz"),
        ]

    def test_restore_when_database_does_not_match_then_nothing_runs(self):
        with patch.object(rs, "run_psql") as psql, patch.object(
            rs, "extract_archive"
        ) as extract:
            with pytest.raises(
                ValueError,
                match="does not match this deployment's database 'evidencelab'",
            ):
                rs.restore(_args(database="evidencelab_dev"), ENV)
        psql.assert_not_called()
        extract.assert_not_called()

    def test_restore_when_unknown_data_source_then_nothing_runs(self):
        with patch.object(
            rs, "configured_folders", return_value=["uneg"]
        ), patch.object(rs, "run_psql") as psql, patch.object(
            rs, "extract_archive"
        ) as extract:
            with pytest.raises(ValueError, match="'wfp' is not a data source"):
                rs.restore(_args(), ENV)
        psql.assert_not_called()
        extract.assert_not_called()

    def test_restore_when_load_fails_then_running_database_not_swapped(self):
        def psql(lines, env, db, *a, **k):
            list(lines)
            if db == "evidencelab_restore":
                raise RuntimeError("psql stopped with exit code 3")

        with patch.object(rs, "configured_folders", return_value=["wfp"]), patch.object(
            rs, "s3_stream", side_effect=lambda b, k: io.BytesIO(b"SELECT 1;\n")
        ), patch.object(
            rs, "extract_archive", return_value=rs.ArchiveCounts(files=1)
        ), patch.object(
            rs, "run_psql", side_effect=psql
        ) as run:
            with pytest.raises(RuntimeError):
                rs.restore(_args(postgres_key="pg.sql"), ENV)
        assert [c.args[2] for c in run.call_args_list] == [
            "postgres",
            "evidencelab_restore",
        ]


class TestMain:
    def test_main_when_inspect_then_prints_summary(self, capsys):
        stream = io.BytesIO(gzip.compress("".join(EXPORT).encode()))
        with patch.object(rs, "s3_stream", return_value=stream) as s3:
            assert rs.main(["inspect", "--postgres-key", "pg.sql.gz"], ENV) == 0
        s3.assert_called_once_with("evidencelab-transfer-1", "pg.sql.gz")
        assert "public.docs_wfp: 2 rows" in capsys.readouterr().out

    def test_main_when_refused_then_exit_one_with_message(self, capsys):
        args = [
            "restore",
            "--postgres-key",
            "p",
            "--data-key",
            "d",
            "--data-source",
            "wfp",
            "--database",
            "other",
        ]
        assert rs.main(args, ENV) == 1
        assert "error: --database 'other' does not match" in capsys.readouterr().err
