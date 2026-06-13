#!/usr/bin/env python3
"""Reconcile WFP document metadata with the corrected Phase 1 evaluation sheet.

A refreshed ``Evaluation list - Phase 1.xlsx`` updated several metadata fields
for already-ingested documents (notably ``Region`` for ~166 docs, plus
``Country``, ``Type``, ``Quality rating``, ``Completion year`` and a couple of
titles). Because document identity is keyed on the PDF filename, those edits do
not flow back into the indexed records automatically. This script re-applies the
sheet's values to the existing documents across every store that holds the
metadata:

  PostgreSQL:
    - docs_<source>.map_*           (mapped columns, e.g. map_region)
    - docs_<source>.<src_* columns> (source-prefixed columns, e.g.
      src_quality_rating)
  Qdrant:
    - documents_<source>  (doc-level payload, all reconciled fields)
    - chunks_<source>     (per-chunk payload, only denormalised fields)

Safety rails:
  * Dry-run by default — nothing is written without ``--apply``.
  * Never nulls a value: a blank sheet cell is skipped, so the ~10 ``Region``
    cells that regressed to blank in the new sheet cannot wipe good data.
  * Token-loss guard: for ``'; '``-separated list fields (Country, Region) a
    new value with *fewer* tokens than the current one is skipped and logged,
    so a malformed sheet row cannot silently drop countries.
  * Known-typo scrub (e.g. ``'Repubic of Türkiye'`` -> ``'Republic of
    Türkiye'``) so the new sheet's typos are not propagated.
  * Idempotent — only values that actually differ are written, and each write
    is scoped by the prior value so concurrent edits are not stomped.

Usage:
    # Dry-run (default): report what would change, write nothing
    python scripts/fixes/fix_wfp_metadata_deltas.py --data-source wfp

    # Apply for real
    python scripts/fixes/fix_wfp_metadata_deltas.py --data-source wfp --apply

    # Limit to specific columns
    python scripts/fixes/fix_wfp_metadata_deltas.py --data-source wfp \
        --fields map_region map_country
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Columns reconciled by default — the mapped fields the new sheet changed that
# exist as physical docs_<source> columns. ``src_*`` fields (e.g. quality
# rating) live only in Qdrant payload / raw JSONB, not as PG columns, and are
# intentionally out of scope here; any requested column that does not exist on
# the table is skipped with a warning (see ``filter_specs_by_columns``).
DEFAULT_FIELDS = [
    "map_region",
    "map_country",
    "map_document_type",
    "map_published_year",
    "map_title",
]

# Fields denormalised onto every chunk payload (verified against a chunks_wfp
# point). Region and src_* fields are doc-level only and are NOT on chunks.
CHUNK_FIELDS = {
    "map_title",
    "map_country",
    "map_document_type",
    "map_published_year",
    "map_language",
    "map_organization",
    "map_theme",
    "map_pdf_url",
    "map_report_url",
}

# Fields stored as ``'; '``-separated lists, subject to the token-loss guard.
LIST_FIELDS = {"map_country", "map_region"}

SEPARATOR = "; "

# Known typos introduced by the new sheet, scrubbed at the token level so they
# are never written. Extend as further bad values are found.
SCRUB = {
    "Repubic of Türkiye": "Republic of Türkiye",
}

_IDENT_RE = re.compile(r"[a-z_]+")

FieldSpec = namedtuple("FieldSpec", "db_column sheet_column on_chunks is_list")
DocRow = namedtuple("DocRow", "doc_id sheet_id current")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB / Qdrant / spreadsheet)
# ---------------------------------------------------------------------------


def normalize_cell(value: Any) -> Optional[str]:
    """Coerce a spreadsheet/DB cell to a trimmed string, or None if empty.

    Handles pandas ``NaN`` (a float that is not equal to itself) and integral
    floats such as a year ``2024.0`` -> ``"2024"`` to match the text columns.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            value = int(value)
    text = str(value).strip()
    return text or None


def tokens(value: str) -> List[str]:
    """Split a ``'; '``-separated list value into non-empty trimmed tokens."""
    return [tok.strip() for tok in value.split(SEPARATOR) if tok.strip()]


def scrub_value(value: str) -> str:
    """Apply the known-typo map token-by-token (works for scalars too)."""
    fixed = [SCRUB.get(tok.strip(), tok.strip()) for tok in value.split(SEPARATOR)]
    return SEPARATOR.join(fixed)


def is_token_loss(current: str, target: str) -> bool:
    """True if ``target`` has fewer list tokens than ``current``.

    Renames that preserve the token count (e.g. ``Laos`` -> ``Lao People's
    Democratic Republic``) are not a loss; only a drop in count is.
    """
    return len(tokens(target)) < len(tokens(current))


def build_targets(
    records: List[Dict[str, Any]], specs: List[FieldSpec]
) -> Dict[str, Dict[str, str]]:
    """Map each sheet ``Id`` to its desired ``{db_column: scrubbed_value}``.

    For duplicate ``Id`` rows (e.g. bilingual pairs) the first non-empty value
    per field wins, so a blank in one language row does not mask a good value.
    """
    targets: Dict[str, Dict[str, str]] = {}
    for row in records:
        sheet_id = normalize_cell(row.get("Id"))
        if sheet_id is None:
            continue
        slot = targets.setdefault(sheet_id, {})
        for spec in specs:
            if spec.db_column in slot:
                continue
            value = normalize_cell(row.get(spec.sheet_column))
            if value is not None:
                slot[spec.db_column] = scrub_value(value)
    return targets


def compute_corrections(
    docs: List[DocRow],
    targets: Dict[str, Dict[str, str]],
    specs: List[FieldSpec],
) -> Tuple[Dict[str, Dict[str, Tuple[Any, str]]], List[Tuple[str, str, str, str]]]:
    """Diff current DB values against sheet targets.

    Returns ``(corrections, skips)`` where ``corrections`` maps
    ``doc_id -> {db_column: (old, new)}`` and ``skips`` records token-loss
    guard hits as ``(doc_id, column, current, target)``.
    """
    spec_by_col = {spec.db_column: spec for spec in specs}
    corrections: Dict[str, Dict[str, Tuple[Any, str]]] = {}
    skips: List[Tuple[str, str, str, str]] = []
    for doc in docs:
        wanted = targets.get(doc.sheet_id, {})
        changes: Dict[str, Tuple[Any, str]] = {}
        for col, target in wanted.items():
            current = doc.current.get(col)
            if not target or current == target:
                continue
            if spec_by_col[col].is_list and current and is_token_loss(current, target):
                skips.append((doc.doc_id, col, str(current), target))
                continue
            changes[col] = (current, target)
        if changes:
            corrections[doc.doc_id] = changes
    return corrections, skips


# ---------------------------------------------------------------------------
# Config / spreadsheet loading
# ---------------------------------------------------------------------------


def resolve_source(config: Dict[str, Any], source: str) -> Tuple[str, Dict[str, Any]]:
    """Resolve a data-source key or subdir against the config whitelist."""
    for key, block in config.get("datasources", {}).items():
        if key == source or block.get("data_subdir") == source:
            return block.get("data_subdir", source), block
    raise SystemExit(f"Unknown data_source: {source!r} (not in config.json)")


def build_specs(block: Dict[str, Any], requested: List[str]) -> List[FieldSpec]:
    """Build field specs from the data source's field mappings."""
    field_map = block.get("field_mapping", {})
    src_map = block.get("src_field_mapping", {})
    specs: List[FieldSpec] = []
    for column in requested:
        if not _IDENT_RE.fullmatch(column):
            raise SystemExit(f"Illegal column name: {column!r}")
        if column.startswith("map_"):
            sheet_col = field_map.get(column[len("map_") :])
        else:
            sheet_col = src_map.get(column)
        if not sheet_col or str(sheet_col).startswith("fixed_value:"):
            logger.warning("No sheet column mapped for %s; skipping it", column)
            continue
        specs.append(
            FieldSpec(column, sheet_col, column in CHUNK_FIELDS, column in LIST_FIELDS)
        )
    return specs


def filter_specs_by_columns(
    specs: List[FieldSpec], available: set
) -> Tuple[List[FieldSpec], List[str]]:
    """Split specs into those whose column exists on the table and those not.

    ``src_*`` and other non-physical fields are dropped here rather than
    crashing the SELECT, and returned in the second list so the caller can warn.
    """
    kept = [spec for spec in specs if spec.db_column in available]
    dropped = [spec.db_column for spec in specs if spec.db_column not in available]
    return kept, dropped


def load_records(excel_path: str) -> List[Dict[str, Any]]:
    """Load the evaluation spreadsheet into a list of row dicts."""
    import pandas as pd  # local import keeps pandas off the import path for tests

    if not os.path.exists(excel_path):
        raise SystemExit(f"Spreadsheet not found: {excel_path}")
    frame = pd.read_excel(excel_path)
    return frame.to_dict(orient="records")


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _postgres_conn():
    import psycopg2  # local import — keeps the import lazy

    try:
        from pipeline.db.postgres_client_base import build_postgres_dsn

        dsn = build_postgres_dsn()
    except ImportError:
        dsn = (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"user={os.environ.get('POSTGRES_USER', 'evidencelab')} "
            f"password={os.environ.get('POSTGRES_PASSWORD', 'evidencelab')} "
            f"dbname={os.environ.get('POSTGRES_DB', 'evidencelab')}"
        )
    return psycopg2.connect(dsn)


def fetch_columns(conn, table: str) -> set:
    """Return the set of physical column names on ``table``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


def fetch_docs(conn, table: str, specs: List[FieldSpec]) -> List[DocRow]:
    """Fetch doc_id, sheet Id, and current values for the reconciled columns."""
    cols = [spec.db_column for spec in specs]
    select = ", ".join(["doc_id", "src_doc_raw_metadata->>'Id'", *cols])
    with conn.cursor() as cur:
        cur.execute(f"SELECT {select} FROM {table}")  # nosec B608 - validated idents
        rows = cur.fetchall()
    docs: List[DocRow] = []
    for row in rows:
        current = {col: row[2 + idx] for idx, col in enumerate(cols)}
        docs.append(DocRow(doc_id=row[0], sheet_id=row[1], current=current))
    return docs


def apply_postgres(
    conn, table: str, corrections: Dict[str, Dict[str, Tuple[Any, str]]], apply: bool
) -> int:
    """Apply corrections to docs_<source>. Returns the field-update count."""
    count = 0
    with conn.cursor() as cur:
        for doc_id, changes in corrections.items():
            for col, (old, new) in changes.items():
                count += 1
                if not apply:
                    continue
                _update_one(cur, table, col, doc_id, old, new)
    if apply:
        conn.commit()
    return count


def _update_one(cur, table: str, col: str, doc_id: str, old: Any, new: str) -> None:
    """Scoped single-column update guarded by the prior value and rowcount."""
    if old is None:
        cur.execute(
            f"UPDATE {table} SET {col} = %s "  # nosec B608 - validated idents
            f"WHERE doc_id = %s AND {col} IS NULL",
            (new, doc_id),
        )
    else:
        cur.execute(
            f"UPDATE {table} SET {col} = %s "  # nosec B608 - validated idents
            f"WHERE doc_id = %s AND {col} = %s",
            (new, doc_id, old),
        )
    if cur.rowcount != 1:
        raise RuntimeError(
            f"Expected to update exactly 1 row for doc_id={doc_id} col={col}, "
            f"got {cur.rowcount}"
        )


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _qdrant_client():
    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    host = host.replace("://qdrant:", "://localhost:")
    return QdrantClient(url=host, api_key=os.getenv("QDRANT_API_KEY"))


def _set_payload_retry(
    client, collection: str, payload: Dict[str, Any], points
) -> None:
    """set_payload with bounded exponential-backoff retries."""
    for attempt in range(5):
        try:
            client.set_payload(
                collection_name=collection, payload=payload, points=points, wait=False
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry any transient Qdrant error
            wait = 2**attempt
            logger.warning(
                "Retry %d for %s: %s (sleep %ds)", attempt + 1, collection, exc, wait
            )
            time.sleep(wait)
    raise RuntimeError(f"Failed to set payload on {collection} for {points}")


def apply_qdrant_documents(
    client,
    collection: str,
    corrections: Dict[str, Dict[str, Tuple[Any, str]]],
    apply: bool,
) -> int:
    """Update doc-level payloads (all reconciled fields). Returns docs touched."""
    count = 0
    for doc_id, changes in corrections.items():
        payload = {col: new for col, (_old, new) in changes.items()}
        count += 1
        if apply:
            _set_payload_retry(client, collection, payload, points=[doc_id])
    return count


def apply_qdrant_chunks(
    client,
    collection: str,
    corrections: Dict[str, Dict[str, Tuple[Any, str]]],
    apply: bool,
) -> int:
    """Update per-chunk payloads (denormalised fields only). Returns docs touched."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    count = 0
    for doc_id, changes in corrections.items():
        payload = {
            col: new for col, (_old, new) in changes.items() if col in CHUNK_FIELDS
        }
        if not payload:
            continue
        count += 1
        if apply:
            flt = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            )
            _set_payload_retry(client, collection, payload, points=flt)
    return count


# ---------------------------------------------------------------------------
# Reporting / main
# ---------------------------------------------------------------------------


def log_plan(
    corrections: Dict[str, Dict[str, Tuple[Any, str]]],
    skips: List[Tuple[str, str, str, str]],
    sample: int = 12,
) -> None:
    """Log per-field change counts, a sample of changes, and skipped rows."""
    per_field: Dict[str, int] = {}
    for changes in corrections.values():
        for col in changes:
            per_field[col] = per_field.get(col, 0) + 1
    logger.info("Documents with changes: %d", len(corrections))
    for col, num in sorted(per_field.items(), key=lambda kv: -kv[1]):
        logger.info("  %-22s %d docs", col, num)

    shown = 0
    for doc_id, changes in corrections.items():
        for col, (old, new) in changes.items():
            if shown >= sample:
                break
            logger.info("  e.g. doc=%s %s: %r -> %r", doc_id, col, old, new)
            shown += 1
        if shown >= sample:
            break

    if skips:
        logger.warning(
            "Skipped %d token-loss change(s) (would drop list items):", len(skips)
        )
        for doc_id, col, current, target in skips[:sample]:
            logger.warning(
                "  doc=%s %s: %r -> %r (skipped)", doc_id, col, current, target
            )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile document metadata with the corrected eval sheet."
    )
    parser.add_argument(
        "--data-source", default="wfp", help="Data source (default: wfp)"
    )
    parser.add_argument(
        "--excel",
        default=None,
        help="Path to the evaluation spreadsheet (default: "
        "$DATA_MOUNT_PATH/<subdir>/Evaluation list - Phase 1.xlsx)",
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        default=DEFAULT_FIELDS,
        help="DB columns to reconcile (default: the changed mapped fields)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry-run)"
    )
    parser.add_argument("--skip-postgres", action="store_true", help="Skip PostgreSQL")
    parser.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant")
    return parser.parse_args(argv)


def _default_excel(subdir: str) -> str:
    mount = os.getenv("DATA_MOUNT_PATH", "./data")
    return os.path.join(mount, subdir, "Evaluation list - Phase 1.xlsx")


def _run_qdrant(
    corrections: Dict[str, Dict[str, Tuple[Any, str]]], subdir: str, apply: bool
) -> Tuple[int, int]:
    client = _qdrant_client()
    docs = apply_qdrant_documents(client, f"documents_{subdir}", corrections, apply)
    chunks = apply_qdrant_chunks(client, f"chunks_{subdir}", corrections, apply)
    return docs, chunks


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
    config_path = os.path.join(os.path.dirname(__file__), "../../config.json")
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

    subdir, block = resolve_source(config, args.data_source)
    specs = build_specs(block, args.fields)
    if not specs:
        raise SystemExit("No reconcilable fields resolved; nothing to do.")
    excel_path = args.excel or _default_excel(subdir)

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("=" * 64)
    logger.info(" WFP metadata reconciliation  [%s]", mode)
    logger.info(" data_source=%s  table=docs_%s  excel=%s", subdir, subdir, excel_path)
    logger.info(" fields=%s", [s.db_column for s in specs])
    logger.info("=" * 64)

    conn = _postgres_conn()
    try:
        specs, dropped = filter_specs_by_columns(
            specs, fetch_columns(conn, f"docs_{subdir}")
        )
        if dropped:
            logger.warning("Skipping non-PG columns (out of scope): %s", dropped)
        if not specs:
            raise SystemExit("No reconcilable PG columns; nothing to do.")
        targets = build_targets(load_records(excel_path), specs)
        docs = fetch_docs(conn, f"docs_{subdir}", specs)
        corrections, skips = compute_corrections(docs, targets, specs)
        log_plan(corrections, skips)
        pg_changes = 0
        if not args.skip_postgres:
            pg_changes = apply_postgres(conn, f"docs_{subdir}", corrections, args.apply)
    finally:
        conn.close()

    qd_docs = qd_chunks = 0
    if not args.skip_qdrant:
        qd_docs, qd_chunks = _run_qdrant(corrections, subdir, args.apply)

    label = "applied" if args.apply else "would change"
    logger.info("-" * 64)
    logger.info(" Summary  [%s]", mode)
    logger.info("   PG docs_%s field-updates %s:   %d", subdir, label, pg_changes)
    logger.info("   Qdrant documents_%s docs %s:   %d", subdir, label, qd_docs)
    logger.info("   Qdrant chunks_%s docs %s:      %d", subdir, label, qd_chunks)
    if not args.apply:
        logger.info(" Re-run with --apply to write these changes.")
    logger.info("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
