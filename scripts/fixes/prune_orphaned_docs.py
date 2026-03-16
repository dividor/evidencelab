#!/usr/bin/env python3
"""
Prune orphaned documents from PostgreSQL and Qdrant.

An orphaned document is one whose file no longer exists on disk (e.g. after
deduplication removed identical-duplicate PDFs). This script:

  1. Queries all doc_ids and their sys_filepath from Postgres
  2. Checks if the file exists on disk
  3. Deletes orphaned docs + their chunks from Postgres (CASCADE)
  4. Deletes orphaned doc points from Qdrant documents collection
  5. Deletes orphaned chunk points from Qdrant chunks collection

Dry-run by default -- pass ``--confirm`` to actually delete.

Usage:
    # Dry-run report
    python scripts/fixes/prune_orphaned_docs.py --source uneg

    # Actually delete
    python scripts/fixes/prune_orphaned_docs.py --source uneg --confirm
"""
import argparse
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402
from pipeline.db.postgres_client import PostgresClient  # noqa: E402


def prune_orphans(data_source: str, confirm: bool = False):
    print(f"\n{'=' * 70}")
    print(f"  Pruning orphaned documents: {data_source}")
    print(f"{'=' * 70}")

    pg = PostgresClient(data_source)
    docs_table = pg.docs_table
    chunks_table = pg.chunks_table

    # ── 1. Find orphaned docs ───────────────────────────────────────────
    print("\nScanning for orphaned documents ...")
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {docs_table}")
            total_docs_before = cur.fetchone()[0]

            cur.execute(f"SELECT COUNT(*) FROM {chunks_table}")
            total_chunks_before = cur.fetchone()[0]

            cur.execute(
                f"""
                SELECT doc_id, map_title, sys_data->>'sys_filepath' as filepath
                FROM {docs_table}
            """
            )
            all_docs = cur.fetchall()

    print(f"  Total docs in DB:   {total_docs_before:,}")
    print(f"  Total chunks in DB: {total_chunks_before:,}")

    orphaned_doc_ids = []
    orphaned_titles = []

    for doc_id, title, filepath in all_docs:
        if not filepath:
            orphaned_doc_ids.append(doc_id)
            orphaned_titles.append(title)
            continue
        if os.path.exists(filepath):
            continue
        # Try common path remappings
        alt = filepath.replace("/mnt/data/", "data/").replace(
            "/mnt/files/evaluation-db/", "data/"
        )
        if not os.path.exists(alt):
            orphaned_doc_ids.append(doc_id)
            orphaned_titles.append(title)

    if not orphaned_doc_ids:
        print("  No orphaned documents found.")
        return 0

    print(f"  Orphaned docs (file missing): {len(orphaned_doc_ids):,}")

    # ── 2. Count chunks that will be removed ────────────────────────────
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            # Count chunks belonging to orphaned docs
            batch_size = 5000
            orphan_chunk_count = 0
            orphan_chunk_ids = []
            for i in range(0, len(orphaned_doc_ids), batch_size):
                batch = orphaned_doc_ids[i : i + batch_size]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"SELECT chunk_id FROM {chunks_table} WHERE doc_id IN ({placeholders})",
                    batch,
                )
                chunk_ids = [row[0] for row in cur.fetchall()]
                orphan_chunk_ids.extend(chunk_ids)
                orphan_chunk_count += len(chunk_ids)

    print(f"  Orphaned chunks:              {orphan_chunk_count:,}")

    # ── 3. Show sample orphans ──────────────────────────────────────────
    print("\n  Sample orphaned documents (first 10):")
    for i in range(min(10, len(orphaned_doc_ids))):
        title_short = (orphaned_titles[i] or "?")[:60]
        print(f"    {orphaned_doc_ids[i][:20]}...  {title_short}")

    # Categorize
    report2 = sum(1 for t in orphaned_titles if t and "report 2" in t.lower())
    print("\n  Breakdown:")
    print(f"    'Report 2' dupes: {report2:,}")
    print(f"    Other:            {len(orphaned_doc_ids) - report2:,}")

    if not confirm:
        print(
            f"\n  DRY RUN -- use --confirm to delete {len(orphaned_doc_ids):,} docs "
            f"and {orphan_chunk_count:,} chunks."
        )
        return len(orphaned_doc_ids)

    # ── 4. Delete chunks from Qdrant ────────────────────────────────────
    print(f"\n  Deleting {orphan_chunk_count:,} chunks from Qdrant ...")
    db = get_db(data_source)
    batch_size = 5000
    qdrant_chunks_deleted = 0
    t0 = time.time()

    for i in range(0, len(orphan_chunk_ids), batch_size):
        batch = orphan_chunk_ids[i : i + batch_size]
        try:
            db.client.delete(
                collection_name=db.chunks_collection,
                points_selector=batch,
                wait=True,
            )
            qdrant_chunks_deleted += len(batch)
        except Exception as e:
            print(f"    Qdrant chunks batch error at offset {i}: {e}")
        if qdrant_chunks_deleted % 10000 < batch_size:
            print(
                f"    Qdrant chunks: {qdrant_chunks_deleted:,}/{orphan_chunk_count:,} ..."
            )

    print(
        f"  Qdrant chunks: deleted {qdrant_chunks_deleted:,} in {time.time() - t0:.1f}s"
    )

    # ── 5. Delete docs from Qdrant ──────────────────────────────────────
    print(f"\n  Deleting {len(orphaned_doc_ids):,} docs from Qdrant ...")
    qdrant_docs_deleted = 0
    t0 = time.time()

    for i in range(0, len(orphaned_doc_ids), batch_size):
        batch = orphaned_doc_ids[i : i + batch_size]
        try:
            db.client.delete(
                collection_name=db.documents_collection,
                points_selector=batch,
                wait=True,
            )
            qdrant_docs_deleted += len(batch)
        except Exception as e:
            print(f"    Qdrant docs batch error at offset {i}: {e}")
        if qdrant_docs_deleted % 10000 < batch_size:
            print(
                f"    Qdrant docs: {qdrant_docs_deleted:,}/{len(orphaned_doc_ids):,} ..."
            )

    print(f"  Qdrant docs: deleted {qdrant_docs_deleted:,} in {time.time() - t0:.1f}s")

    # ── 6. Delete from Postgres (CASCADE deletes chunks too) ────────────
    print(f"\n  Deleting {len(orphaned_doc_ids):,} docs from Postgres (CASCADE) ...")
    pg_deleted = 0
    t0 = time.time()

    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(orphaned_doc_ids), batch_size):
                batch = orphaned_doc_ids[i : i + batch_size]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"DELETE FROM {docs_table} WHERE doc_id IN ({placeholders})",
                    batch,
                )
                pg_deleted += cur.rowcount
                if pg_deleted % 10000 < batch_size:
                    print(f"    Postgres: {pg_deleted:,}/{len(orphaned_doc_ids):,} ...")
        conn.commit()

    pg_elapsed = time.time() - t0
    print(
        f"  Postgres: deleted {pg_deleted:,} docs (+ cascaded chunks) in {pg_elapsed:.1f}s"
    )

    # ── 7. Verify ───────────────────────────────────────────────────────
    print("\n  Verifying ...")
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {docs_table}")
            docs_after = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {chunks_table}")
            chunks_after = cur.fetchone()[0]

    qdrant_docs_after = db.client.count(collection_name=db.documents_collection).count
    qdrant_chunks_after = db.client.count(collection_name=db.chunks_collection).count

    print(
        f"  Postgres docs:   {total_docs_before:,} -> {docs_after:,} "
        f"(removed {total_docs_before - docs_after:,})"
    )
    print(
        f"  Postgres chunks: {total_chunks_before:,} -> {chunks_after:,} "
        f"(removed {total_chunks_before - chunks_after:,})"
    )
    print(f"  Qdrant docs:     {qdrant_docs_after:,}")
    print(f"  Qdrant chunks:   {qdrant_chunks_after:,}")

    return len(orphaned_doc_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prune orphaned documents from PostgreSQL and Qdrant"
    )
    parser.add_argument(
        "--source",
        default="uneg",
        help="Data source (default: uneg)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete orphans (default is dry-run).",
    )
    args = parser.parse_args()

    try:
        count = prune_orphans(args.source, confirm=args.confirm)
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print(f"\n{'=' * 70}")
    action = "Deleted" if args.confirm else "Found"
    print(f"  {action} {count:,} orphaned documents.")
    print(f"{'=' * 70}\n")
