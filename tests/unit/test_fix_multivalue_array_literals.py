"""Unit tests for scripts/fixes/fix_multivalue_array_literals.py.

The parsing tests use the script's functions directly. The database tests run
the script's real code against small in-memory stand-ins for the PostgreSQL
docs table and the two Qdrant collections.
"""

import contextlib
import importlib.util
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from psycopg2 import sql
from qdrant_client import models

# The script lives under scripts/fixes/ (not a package); import it by path.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "fixes"
    / "fix_multivalue_array_literals.py"
)
_spec = importlib.util.spec_from_file_location(
    "fix_multivalue_array_literals", _SCRIPT_PATH
)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)

pytestmark = pytest.mark.unit

FOOD_GENDER = '{"Food systems",Gender}'
GENDER_NUTRITION = "{Gender,Nutrition}"


# ---------------------------------------------------------------------------
# In-memory stand-ins
# ---------------------------------------------------------------------------


def _parts(query: sql.Composed) -> List[Any]:
    return list(query.seq)


def _identifiers(query: sql.Composed) -> List[str]:
    return [
        part.strings[0] for part in _parts(query) if isinstance(part, sql.Identifier)
    ]


class FakeCursor:
    """Runs the script's three kinds of statement against ``FakeConn.rows``."""

    def __init__(self, conn: "FakeConn"):
        self.conn = conn
        self.result: List[Any] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=()):
        self.conn.executed.append((query, params))
        if isinstance(query, str):
            self.result = [(name,) for name in self.conn.columns]
            return
        names = _identifiers(query)
        assert self.conn.table in names
        column = next(name for name in names if name != self.conn.table)
        verb = _parts(query)[0].string.split()[0]
        if verb == "SELECT":
            assert params == ("{%}",)
            found = Counter(
                row[column]
                for row in self.conn.rows
                if isinstance(row.get(column), str)
                and row[column].startswith("{")
                and row[column].endswith("}")
            )
            self.result = list(found.items())
        else:
            assert verb == "UPDATE"
            if self.conn.fail_updates:
                raise RuntimeError("database went away")
            new, old = params
            matched = [row for row in self.conn.rows if row.get(column) == old]
            for row in matched:
                row[column] = new
            self.rowcount = len(matched)

    def fetchall(self):
        return self.result


class FakeConn:
    def __init__(self, table: str, columns: List[str], rows: List[Dict[str, Any]]):
        self.table = table
        self.columns = columns
        self.rows = rows
        self.executed: List[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_updates = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakePoint:
    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload


class FakeQdrant:
    """Scroll in pages and set_payload by a single MatchValue filter."""

    def __init__(self, collections: Dict[str, List[Dict[str, Any]]], page: int = 2):
        self.collections = collections
        self.page = page
        self.set_calls: List[Dict[str, Any]] = []
        self.scroll_payloads: List[Any] = []

    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        assert with_vectors is False
        self.scroll_payloads.append(with_payload)
        points = self.collections[collection_name]
        start = offset or 0
        end = min(start + self.page, len(points))
        page = [
            FakePoint({k: v for k, v in p.items() if k in with_payload})
            for p in points[start:end]
        ]
        return page, (end if end < len(points) else None)

    def set_payload(self, collection_name, payload, points, wait):
        assert wait is True
        self.set_calls.append(
            {"collection": collection_name, "payload": payload, "points": points}
        )
        condition = points.must[0]
        for point in self.collections[collection_name]:
            if point.get(condition.key) == condition.match.value:
                point.update(payload)


class FakePg:
    def __init__(self, conn: FakeConn):
        self.docs_table = conn.table
        self._conn = conn

    @contextlib.contextmanager
    def _get_conn(self):
        yield self._conn


class FakeDb:
    def __init__(self, rows, documents, chunks, columns=("map_country", "map_theme")):
        self.pg = FakePg(FakeConn("docs_demo", list(columns), rows))
        self.documents_collection = "documents_demo"
        self.chunks_collection = "chunks_demo"
        self.client = FakeQdrant({"documents_demo": documents, "chunks_demo": chunks})


def _make_db(theme_values: List[Optional[str]]) -> FakeDb:
    rows = [
        {"doc_id": str(i), "map_theme": v, "map_country": "Mali"}
        for i, v in enumerate(theme_values)
    ]
    documents = [{"map_theme": v, "map_country": "Mali"} for v in theme_values]
    chunks = [
        {"map_theme": v, "map_country": "Mali"} for v in theme_values for _ in range(3)
    ]
    return FakeDb(rows, documents, chunks)


@pytest.fixture
def run_main(monkeypatch):
    """Run the script's main() against a FakeDb for data source ``demo``."""

    def _run(db: FakeDb, *argv: str, source: str = "demo") -> int:
        def _database(name, create_indexes):
            assert (name, create_indexes) == ("demo", False)
            return db

        monkeypatch.setattr(fix, "Database", _database)
        monkeypatch.setattr(
            fix,
            "load_datasources_config",
            lambda: {"datasources": {"Demo": {"data_subdir": "demo"}}},
        )
        return fix.main(["--data-source", source, *argv])

    return _run


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseArrayLiteral:
    @pytest.mark.parametrize(
        "text, expected",
        [
            (GENDER_NUTRITION, ["Gender", "Nutrition"]),
            (FOOD_GENDER, ["Food systems", "Gender"]),
            ("{Gender}", ["Gender"]),
            ('{"Egypt, Arab Rep.",Gambia}', ["Egypt, Arab Rep.", "Gambia"]),
            ('{"Côte d\'Ivoire",Mali}', ["Côte d'Ivoire", "Mali"]),
            ('{"say \\"hi\\"","back\\\\slash"}', ['say "hi"', "back\\slash"]),
        ],
    )
    def test_parse_array_literal_when_valid_then_values_in_order(self, text, expected):
        assert fix.parse_array_literal(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Gender",
            "{}",
            "{NULL,Gender}",
            "{Gender,}",
            "{,Gender}",
            '{"Food systems}',
            "{{a,b},{c,d}}",
            "{Food systems}",
            '{"Food"x}',
            '{"Food\\}',
        ],
    )
    def test_parse_array_literal_when_malformed_then_raises(self, text):
        with pytest.raises(fix.ArrayLiteralError):
            fix.parse_array_literal(text)


class TestToJoined:
    def test_to_joined_when_valid_then_semicolon_joined(self):
        assert fix.to_joined(FOOD_GENDER) == "Food systems; Gender"

    def test_to_joined_when_single_value_then_value_itself(self):
        assert fix.to_joined("{Gender}") == "Gender"

    @pytest.mark.parametrize("text", ['{"",Gender}', '{" ",Gender}', '{"a;b",Gender}'])
    def test_to_joined_when_value_empty_or_has_semicolon_then_raises(self, text):
        with pytest.raises(fix.ArrayLiteralError):
            fix.to_joined(text)


class TestLooksLikeArrayLiteral:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (GENDER_NUTRITION, True),
            ("Gender; Nutrition", False),
            ("Gender", False),
            (["Gender", "Nutrition"], False),
            (None, False),
            ("{open", False),
        ],
    )
    def test_looks_like_array_literal(self, value, expected):
        assert fix.looks_like_array_literal(value) is expected


class TestBuildMappings:
    def test_build_mappings_when_values_repeat_across_places_then_one_entry_each(self):
        places = [
            fix.Place("docs_demo", {"map_theme": Counter({FOOD_GENDER: 2})}),
            fix.Place(
                "chunks_demo",
                {"map_theme": Counter({FOOD_GENDER: 9, GENDER_NUTRITION: 4})},
            ),
        ]
        mappings, problems = fix.build_mappings(places)
        assert problems == []
        assert mappings == {
            "map_theme": {
                FOOD_GENDER: "Food systems; Gender",
                GENDER_NUTRITION: "Gender; Nutrition",
            }
        }

    def test_build_mappings_when_value_unparseable_then_reported_as_problem(self):
        places = [fix.Place("docs_demo", {"map_theme": Counter({"{NULL,Gender}": 1})})]
        mappings, problems = fix.build_mappings(places)
        assert mappings == {}
        assert problems == [("map_theme", "{NULL,Gender}", "NULL value")]


# ---------------------------------------------------------------------------
# PostgreSQL and Qdrant helpers
# ---------------------------------------------------------------------------


class TestPostgres:
    def test_pg_map_columns_when_mixed_columns_then_only_map_columns(self):
        conn = FakeConn("docs_demo", ["map_country", "sys_summary", "map_theme"], [])
        assert fix.pg_map_columns(conn, "docs_demo") == ["map_country", "map_theme"]
        _, params = conn.executed[0]
        assert params == ("docs_demo",)

    def test_pg_literal_counts_when_some_literals_then_counts_only_those(self):
        db = _make_db([FOOD_GENDER, FOOD_GENDER, "Gender; Nutrition", None])
        counts = fix.pg_literal_counts(
            db.pg._conn, "docs_demo", ["map_country", "map_theme"]
        )
        assert counts == {"map_theme": Counter({FOOD_GENDER: 2})}

    def test_pg_apply_when_mapped_then_rows_rewritten_and_committed(self):
        db = _make_db([FOOD_GENDER, FOOD_GENDER, "Gender"])
        conn = db.pg._conn
        changed = fix.pg_apply(
            conn, "docs_demo", {"map_theme": {FOOD_GENDER: "Food systems; Gender"}}
        )
        assert changed == 2
        assert [r["map_theme"] for r in conn.rows] == ["Food systems; Gender"] * 2 + [
            "Gender"
        ]
        assert (conn.commits, conn.rollbacks) == (1, 0)

    def test_pg_apply_when_update_fails_then_rolled_back_and_raised(self):
        db = _make_db([FOOD_GENDER])
        conn = db.pg._conn
        conn.fail_updates = True
        with pytest.raises(RuntimeError):
            fix.pg_apply(
                conn, "docs_demo", {"map_theme": {FOOD_GENDER: "Food systems; Gender"}}
            )
        assert (conn.commits, conn.rollbacks) == (0, 1)


class TestQdrant:
    def test_qdrant_literal_counts_when_several_pages_then_all_counted(self):
        db = _make_db([FOOD_GENDER, GENDER_NUTRITION, "Gender", FOOD_GENDER, None])
        counts = fix.qdrant_literal_counts(db.client, "chunks_demo", ["map_theme"])
        assert counts == {"map_theme": Counter({FOOD_GENDER: 6, GENDER_NUTRITION: 3})}
        assert db.client.scroll_payloads[0] == ["map_theme"]

    def test_qdrant_apply_when_mapped_then_one_filtered_call_per_value(self):
        db = _make_db([FOOD_GENDER, "Gender"])
        fix.qdrant_apply(
            db.client,
            "chunks_demo",
            {"map_theme": {FOOD_GENDER: "Food systems; Gender"}},
        )
        assert len(db.client.set_calls) == 1
        call = db.client.set_calls[0]
        assert call["payload"] == {"map_theme": "Food systems; Gender"}
        condition = call["points"].must[0]
        assert isinstance(condition.match, models.MatchValue)
        assert (condition.key, condition.match.value) == ("map_theme", FOOD_GENDER)
        themes = [p["map_theme"] for p in db.client.collections["chunks_demo"]]
        assert themes == ["Food systems; Gender"] * 3 + ["Gender"] * 3


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _all_themes(db: FakeDb) -> List[Optional[str]]:
    return (
        [r["map_theme"] for r in db.pg._conn.rows]
        + [p["map_theme"] for p in db.client.collections["documents_demo"]]
        + [p["map_theme"] for p in db.client.collections["chunks_demo"]]
    )


class TestMain:
    def test_main_when_dry_run_then_nothing_written(self, run_main):
        db = _make_db([FOOD_GENDER, GENDER_NUTRITION, "Gender"])
        before = _all_themes(db)
        assert run_main(db) == 0
        assert _all_themes(db) == before
        assert db.client.set_calls == []
        assert db.pg._conn.commits == 0

    def test_main_when_apply_then_every_place_rewritten(self, run_main):
        db = _make_db([FOOD_GENDER, GENDER_NUTRITION, "Gender", None])
        assert run_main(db, "--apply") == 0
        assert [r["map_theme"] for r in db.pg._conn.rows] == [
            "Food systems; Gender",
            "Gender; Nutrition",
            "Gender",
            None,
        ]
        assert not any(fix.looks_like_array_literal(v) for v in _all_themes(db))
        assert all(r["map_country"] == "Mali" for r in db.pg._conn.rows)

    def test_main_when_run_again_after_apply_then_no_writes(self, run_main):
        db = _make_db([FOOD_GENDER])
        assert run_main(db, "--apply") == 0
        writes = len(db.client.set_calls)
        assert run_main(db, "--apply") == 0
        assert len(db.client.set_calls) == writes

    def test_main_when_a_value_cannot_be_parsed_then_stops_before_writing(
        self, run_main
    ):
        db = _make_db([FOOD_GENDER, "{NULL,Gender}"])
        before = _all_themes(db)
        assert run_main(db, "--apply") == 2
        assert _all_themes(db) == before
        assert db.client.set_calls == []

    def test_main_when_literals_remain_after_apply_then_exit_code_1(
        self, run_main, monkeypatch
    ):
        db = _make_db([FOOD_GENDER])
        monkeypatch.setattr(db.client, "set_payload", lambda **kwargs: None)
        assert run_main(db, "--apply") == 1

    def test_main_when_unknown_data_source_then_exits(self, run_main):
        db = _make_db([FOOD_GENDER])
        with pytest.raises(SystemExit):
            run_main(db, "--apply", source="nope")
        assert db.client.set_calls == []
        assert db.pg._conn.executed == []
