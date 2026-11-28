#!/usr/bin/env python3
"""Rewrite multi-value fields stored as PostgreSQL array literals.

A document field can hold several values, for example a theme of
``Gender; Nutrition``. The scanner splits such a value into a list. Until
17 March 2026 (commit ba557060) that list reached the PostgreSQL TEXT column
as it was, and psycopg2 wrote it as an array literal: ``{Gender,Nutrition}``,
or ``{"Food systems",Gender}`` when a value has a space in it. Documents
processed before that fix, and every copy made of their data, can still hold
this form, in three places:

  * PostgreSQL ``docs_<source>``: the ``map_*`` column
  * Qdrant ``documents_<source>``: the ``map_*`` payload key
  * Qdrant ``chunks_<source>``: the ``map_*`` payload key on each chunk

The app expects one ``"; "``-joined string, ``Food systems; Gender``: the
filter list splits it into separate values, and choosing a value matches every
stored string that contains it. An array literal is neither split nor matched,
so the filter list shows combined values such as ``{"Food systems",Gender}``
and filtering on ``Gender`` misses those documents.

This script rewrites each array literal as the ``"; "``-joined string, keeping
the values in their original order.

Safety:
  * Dry run by default. Nothing is written without ``--apply``.
  * Every value wrapped in ``{...}`` must parse as an array literal of
    non-empty values with no ``;`` in them. If any does not, the script lists
    them and stops before writing anything.
  * Only values still in array-literal form are changed, so a second run
    changes nothing.
  * After ``--apply`` it scans again and exits with code 1 if any remain.

Usage (where ``pipeline.db`` can reach the databases, such as the pipeline
container):

    # Dry run: report what would change, write nothing
    python scripts/fixes/fix_multivalue_array_literals.py --data-source <name>

    # Write the changes
    python scripts/fixes/fix_multivalue_array_literals.py --data-source <name> --apply
"""

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from psycopg2 import sql
from qdrant_client import models

from pipeline.db import Database
from pipeline.db.config import load_datasources_config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SCROLL_PAGE = 512
_UNQUOTED_FORBIDDEN = set('{}"\\')

# field -> stored value -> number of rows or points holding it
FieldCounts = Dict[str, Counter[str]]


class ArrayLiteralError(ValueError):
    """A value wrapped in braces that is not a usable array literal."""


@dataclass
class Place:
    """One table or collection and the array-literal values found in it."""

    name: str
    counts: FieldCounts


# ---------------------------------------------------------------------------
# Parsing (no database needed)
# ---------------------------------------------------------------------------


def looks_like_array_literal(value: object) -> bool:
    """True for a string wrapped in braces, the form psycopg2 gave lists."""
    return isinstance(value, str) and value.startswith("{") and value.endswith("}")


def _read_quoted(body: str, pos: int) -> Tuple[str, int]:
    """Read a quoted value whose opening quote is just before ``pos``."""
    chars: List[str] = []
    while pos < len(body):
        char = body[pos]
        if char == "\\":
            if pos + 1 == len(body):
                raise ArrayLiteralError("backslash at the end of a quoted value")
            chars.append(body[pos + 1])
            pos += 2
        elif char == '"':
            return "".join(chars), pos + 1
        else:
            chars.append(char)
            pos += 1
    raise ArrayLiteralError("quoted value has no closing quote")


def _read_unquoted(body: str, pos: int) -> Tuple[str, int]:
    """Read an unquoted value, which runs to the next comma."""
    end = pos
    while end < len(body) and body[end] != ",":
        if body[end] in _UNQUOTED_FORBIDDEN or body[end].isspace():
            raise ArrayLiteralError(f"unexpected {body[end]!r} in an unquoted value")
        end += 1
    item = body[pos:end]
    if not item:
        raise ArrayLiteralError("empty value")
    if item.upper() == "NULL":
        raise ArrayLiteralError("NULL value")
    return item, end


def parse_array_literal(text: str) -> List[str]:
    """Parse PostgreSQL's text form of a one-dimensional text array.

    ``{"Food systems",Gender}`` gives ``["Food systems", "Gender"]``. Raises
    ``ArrayLiteralError`` for anything else, including nested arrays and NULLs.
    """
    if not looks_like_array_literal(text):
        raise ArrayLiteralError("not wrapped in braces")
    body = text[1:-1]
    if not body:
        raise ArrayLiteralError("no values")
    items: List[str] = []
    pos = 0
    while True:
        if body[pos] == '"':
            item, pos = _read_quoted(body, pos + 1)
        else:
            item, pos = _read_unquoted(body, pos)
        items.append(item)
        if pos == len(body):
            return items
        if body[pos] != ",":
            raise ArrayLiteralError(f"expected a comma at position {pos + 1}")
        pos += 1
        if pos == len(body):
            raise ArrayLiteralError("comma at the end")


def to_joined(text: str) -> str:
    """The ``"; "``-joined string the app expects for an array literal."""
    items = parse_array_literal(text)
    for item in items:
        if not item.strip():
            raise ArrayLiteralError("empty value")
        if ";" in item:
            raise ArrayLiteralError(f"value {item!r} contains ';'")
    return "; ".join(items)


def build_mappings(
    places: Iterable[Place],
) -> Tuple[Dict[str, Dict[str, str]], List[Tuple[str, str, str]]]:
    """Map each array literal to its joined form, per field.

    Returns ``(mappings, problems)``: ``mappings[field][old] = new``, and one
    ``(field, value, reason)`` for each value that cannot be rewritten.
    """
    mappings: Dict[str, Dict[str, str]] = {}
    problems: List[Tuple[str, str, str]] = []
    for place in places:
        for field, values in place.counts.items():
            for value in values:
                if value in mappings.get(field, {}):
                    continue
                try:
                    mappings.setdefault(field, {})[value] = to_joined(value)
                except ArrayLiteralError as exc:
                    problems.append((field, value, str(exc)))
    return mappings, problems


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def pg_map_columns(conn, table: str) -> List[str]:
    """The text ``map_*`` columns of ``table``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s"
            " AND data_type IN ('text', 'character varying')"
            " ORDER BY column_name",
            (table,),
        )
        return [row[0] for row in cur.fetchall() if row[0].startswith("map_")]


def pg_literal_counts(conn, table: str, columns: List[str]) -> FieldCounts:
    """Rows per array-literal value, for each column."""
    counts: FieldCounts = {}
    with conn.cursor() as cur:
        for column in columns:
            query = sql.SQL(
                "SELECT {col}, count(*) FROM {table} WHERE {col} LIKE %s GROUP BY {col}"
            ).format(col=sql.Identifier(column), table=sql.Identifier(table))
            cur.execute(query, ("{%}",))
            found = Counter({value: n for value, n in cur.fetchall()})
            if found:
                counts[column] = found
    return counts


def pg_apply(conn, table: str, mappings: Dict[str, Dict[str, str]]) -> int:
    """Rewrite every mapped value in one transaction; returns rows changed."""
    changed = 0
    try:
        with conn.cursor() as cur:
            for column, mapping in mappings.items():
                query = sql.SQL(
                    "UPDATE {table} SET {col} = %s WHERE {col} = %s"
                ).format(col=sql.Identifier(column), table=sql.Identifier(table))
                for old, new in mapping.items():
                    cur.execute(query, (new, old))
                    changed += cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return changed


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def qdrant_literal_counts(client, collection: str, fields: List[str]) -> FieldCounts:
    """Points per array-literal value, for each payload field."""
    counts: FieldCounts = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=SCROLL_PAGE,
            offset=offset,
            with_payload=fields,
            with_vectors=False,
        )
        for point in points:
            for field, value in (point.payload or {}).items():
                if looks_like_array_literal(value):
                    counts.setdefault(field, Counter())[value] += 1
        if offset is None:
            return counts


def qdrant_apply(client, collection: str, mappings: Dict[str, Dict[str, str]]) -> None:
    """Rewrite every point holding a mapped value, one call per value."""
    for field, mapping in mappings.items():
        for old, new in mapping.items():
            client.set_payload(
                collection_name=collection,
                payload={field: new},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key=field, match=models.MatchValue(value=old)
                        )
                    ]
                ),
                wait=True,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def gather(db, fields: List[str]) -> List[Place]:
    """Array-literal values in the docs table and both collections."""
    with db.pg._get_conn() as conn:
        pg_counts = pg_literal_counts(conn, db.pg.docs_table, fields)
    return [
        Place(db.pg.docs_table, pg_counts),
        Place(
            db.documents_collection,
            qdrant_literal_counts(db.client, db.documents_collection, fields),
        ),
        Place(
            db.chunks_collection,
            qdrant_literal_counts(db.client, db.chunks_collection, fields),
        ),
    ]


def total_found(places: Iterable[Place]) -> int:
    return sum(sum(c.values()) for place in places for c in place.counts.values())


def report(places: List[Place], mappings: Dict[str, Dict[str, str]]) -> None:
    for place in places:
        for field, values in sorted(place.counts.items()):
            logger.info(
                "%s.%s: %d row(s) or point(s), %d distinct value(s)",
                place.name,
                field,
                sum(values.values()),
                len(values),
            )
    for field, mapping in sorted(mappings.items()):
        logger.info("%s: %d distinct value(s) to rewrite", field, len(mapping))
        for old, new in sorted(mapping.items()):
            counts = ", ".join(
                f"{place.name}={place.counts.get(field, Counter())[old]}"
                for place in places
            )
            logger.info("  %s -> %s  [%s]", old, new, counts)


def validate_source(name: str) -> str:
    """``name`` if config.json has a data source by that name (its data_subdir)."""
    datasources = load_datasources_config().get("datasources", {})
    configured = [conf.get("data_subdir") or key for key, conf in datasources.items()]
    if name not in configured:
        raise SystemExit(
            f"Unknown data source {name!r}. Configured: {sorted(configured)}"
        )
    return name


def apply_all(db, mappings: Dict[str, Dict[str, str]]) -> None:
    with db.pg._get_conn() as conn:
        rows = pg_apply(conn, db.pg.docs_table, mappings)
    logger.info("%s: %d row(s) rewritten", db.pg.docs_table, rows)
    for collection in (db.documents_collection, db.chunks_collection):
        qdrant_apply(db.client, collection, mappings)
        logger.info("%s: rewritten", collection)


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite multi-value fields stored as PostgreSQL array literals."
    )
    parser.add_argument("--data-source", required=True, help="Data source name")
    parser.add_argument(
        "--apply", action="store_true", help="Write the changes (default: dry run)"
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    # create_indexes=False: the script only reads and rewrites payload values.
    db = Database(validate_source(args.data_source), create_indexes=False)
    with db.pg._get_conn() as conn:
        fields = pg_map_columns(conn, db.pg.docs_table)
    logger.info(
        "Mode: %s. Fields checked: %s", "APPLY" if args.apply else "DRY RUN", fields
    )

    places = gather(db, fields)
    mappings, problems = build_mappings(places)
    report(places, mappings)
    if problems:
        for field, value, reason in problems:
            logger.error("Cannot rewrite %s value %r: %s", field, value, reason)
        logger.error(
            "Stopped before writing anything: %d value(s) need a look", len(problems)
        )
        return 2
    if not mappings:
        logger.info("No array-literal values found. Nothing to do.")
        return 0
    if not args.apply:
        logger.info(
            "Dry run: nothing written. Re-run with --apply to write these changes."
        )
        return 0

    apply_all(db, mappings)
    left = total_found(gather(db, fields))
    if left:
        logger.error("%d array-literal value(s) still present after the rewrite", left)
        return 1
    logger.info("Done: no array-literal values remain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
