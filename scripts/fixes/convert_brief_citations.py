#!/usr/bin/env python3
"""Convert stored briefs to citation format 2 (dry run by default).

Before format 2 a brief kept the agent's per-section numbering and only the
browser renumbered citations. This script runs the same conversion the
Alembic data migration applies on deploy (``brief_citations_convert``), but
as a reviewable step: it reports per brief what the conversion would do and,
given the browser's own rendering of the same rows, whether the API's
renumbering matches it.

Steps, run from the repo root inside the api/pipeline container (it reads
the POSTGRES_* environment like the API):

    # 1. Dump the legacy rows for the browser-side harness
    python scripts/fixes/convert_brief_citations.py --dump /tmp/briefs.json
    # 2. Render them with the frozen buildGlobalCitations (see
    #    scripts/fixes/brief_citations_legacy/run.ts)
    # 3. Dry run with the comparison
    python scripts/fixes/convert_brief_citations.py --compare /tmp/legacy.json
    # 4. Apply, backing every old row up first
    python scripts/fixes/convert_brief_citations.py --apply --backup-dir <dir>

Nothing is written without ``--apply``; ``--apply`` refuses to run without a
backup directory, converts each brief in its own transaction and rewrites the
brief's Activity row from the converted content (as the API does on every
save), also for briefs already in format 2.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ui.backend.services.brief_citations_convert import (  # noqa: E402
    compare_with_legacy,
    convert_legacy,
    is_legacy,
    refresh_activity_row,
)


def _database_url() -> str:
    """Same environment the API reads (ui/backend/auth/db.py), sync driver."""
    user = quote_plus(os.environ.get("POSTGRES_USER", "evidencelab"))
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", "evidencelab"))
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("POSTGRES_DBNAME") or os.environ.get(
        "POSTGRES_DB", "evidencelab"
    )
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def load_briefs(engine, brief_id: Optional[str]) -> List[Dict[str, Any]]:
    from sqlalchemy import text

    sql = "SELECT id::text AS id, user_id, title, content FROM briefs"
    params: Dict[str, Any] = {}
    if brief_id:
        sql += " WHERE id = :id"
        params["id"] = brief_id
    sql += " ORDER BY updated_at"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def _print_report(
    brief: Dict[str, Any], report: Dict[str, Any], comparison: Optional[Dict[str, Any]]
) -> None:
    print(f"\n== {brief['id']}  {brief['title'][:70]}")
    print(
        f"   markers {report['markers']}, no source {report['markersNoSource']}, "
        f"source records without chunk id {report['sourcesNoChunkId']}, "
        f"registered sources {report['sourcesRegistered']}, "
        f"{report['bytesBefore'] / 1024:,.0f} KB -> {report['bytesAfter'] / 1024:,.0f} KB"
    )
    for section in report["sections"]:
        unresolved = (
            f" unresolved {section['unresolved']}" if section["unresolved"] else ""
        )
        verdict = (
            f"  [{comparison['sections'].get(section['id'], '?')}]"
            if comparison
            else ""
        )
        print(
            f"   - {section['title'][:50]:50s} markers {section['markers']:3d} "
            f"records {section['sourceRecords']:3d}{unresolved}{verdict}"
        )
    if comparison:
        print(
            f"   references match browser: {comparison['referencesEqual']} "
            f"(api {comparison['referenceCount'][0]}, browser {comparison['referenceCount'][1]})"
        )


def _apply(
    engine, brief: Dict[str, Any], converted: Dict[str, Any], backup_dir: Path
) -> bool:
    """Write the converted brief and refresh its Activity row in one
    transaction; returns whether an Activity row was refreshed."""
    from sqlalchemy import text

    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f"{brief['id']}.json").write_text(json.dumps(brief["content"]))
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE briefs SET content = CAST(:content AS jsonb) WHERE id = :id"),
            {"content": json.dumps(converted), "id": brief["id"]},
        )
        return refresh_activity_row(
            conn, brief["id"], brief["user_id"], brief["title"], converted
        )


def _refresh_activity(engine, brief: Dict[str, Any]) -> bool:
    """Refresh the Activity row of a brief already in format 2."""
    with engine.begin() as conn:
        return refresh_activity_row(
            conn, brief["id"], brief["user_id"], brief["title"], brief["content"]
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the converted briefs (default: dry run)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="where --apply backs each old content up (required)",
    )
    parser.add_argument("--brief-id", help="convert only this brief")
    parser.add_argument(
        "--dump", type=Path, help="write the legacy rows to this JSON file and exit"
    )
    parser.add_argument(
        "--compare", type=Path, help="legacy.json from the browser-side harness"
    )
    parser.add_argument(
        "--report-json", type=Path, help="also write the full report here"
    )
    args = parser.parse_args(argv)
    if args.apply and not args.backup_dir:
        parser.error("--apply requires --backup-dir")

    from sqlalchemy import create_engine

    engine = create_engine(_database_url())
    briefs = load_briefs(engine, args.brief_id)
    if args.dump:
        args.dump.write_text(json.dumps(briefs, default=str))
        print(f"wrote {len(briefs)} briefs to {args.dump}")
        return 0
    legacy = json.loads(args.compare.read_text()) if args.compare else {}
    reports = []
    for brief in briefs:
        if not is_legacy(brief["content"]):
            refreshed = _refresh_activity(engine, brief) if args.apply else None
            note = (
                ""
                if refreshed is None
                else f"; activity row {'refreshed' if refreshed else 'absent'}"
            )
            print(f"\n== {brief['id']}  already format 2, content left as is{note}")
            continue
        converted, report = convert_legacy(brief["content"])
        comparison = (
            compare_with_legacy(converted, legacy[brief["id"]])
            if brief["id"] in legacy
            else None
        )
        _print_report(brief, report, comparison)
        reports.append(
            {
                "id": brief["id"],
                "title": brief["title"],
                **report,
                "comparison": comparison,
            }
        )
        if args.apply:
            refreshed = _apply(engine, brief, converted, args.backup_dir)
            print(f"   applied; activity row {'refreshed' if refreshed else 'absent'}")
    if args.report_json:
        args.report_json.write_text(json.dumps(reports, indent=1))
    print(
        f"\n{'applied' if args.apply else 'dry run'}: {len(reports)} brief(s) converted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
