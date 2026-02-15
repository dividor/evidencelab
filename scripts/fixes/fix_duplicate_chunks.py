#!/usr/bin/env python3
"""
Fix duplicate chunks in both PostgreSQL and Qdrant.

Duplicate chunks are identified as rows sharing the same (doc_id, sys_page_num,
sys_text) in the Postgres chunks table. For each group of duplicates we keep one
chunk_id (the lexicographically smallest) and delete the rest from both
PostgreSQL and the Qdrant chunks collection.

Dry-run by default -- pass ``--confirm`` to actually delete.

Usage:
    # Dry-run report (default)
    python scripts/fixes/fix_duplicate_chunks.py

    # Single data source
    python scripts/fixes/fix_duplicate_chunks.py --source uneg

    # Actually delete
    python scripts/fixes/fix_duplicate_chunks.py --confirm
"""
import argparse
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402
from pipeline.db.postgres_client import PostgresClient  # noqa: E402


def fix_duplicates(data_source: str, confirm: bool = False):
    print(f"\n{'=' * 70}")
    print(f"  Fixing duplicate chunks: {data_source}")
    print(f"{'=' * 70}")

    pg = PostgresClient(data_source)
    table = pg.chunks_table

    # ── 1. Discover duplicates via Postgres ───────────────────────────────
    print("\nScanning for duplicate chunks in Postgres ...")
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            total_before = cur.fetchone()[0]
            print(f"  Total chunks: {total_before:,}")

            # Identify chunk_ids to DELETE (all but the min chunk_id per group)
            # We use md5(sys_text) to avoid comparing huge text blobs in memory.
            cur.execute(
                f"""
                SELECT chunk_id
                FROM (
                    SELECT chunk_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY doc_id, sys_page_num, md5(sys_text)
                               ORDER BY chunk_id
                           ) AS rn
                    FROM {table}
                ) ranked
                WHERE rn > 1
            """
            )
            ids_to_delete = [row[0] for row in cur.fetchall()]

    dupe_count = len(ids_to_delete)
    if dupe_count == 0:
        print("  No duplicates found.")
        return 0

    print(f"  Duplicate chunk_ids to remove: {dupe_count:,}")
    print(f"  Chunks after cleanup: {total_before - dupe_count:,}")

    # ── 2. Show top affected documents ────────────────────────────────────
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            # Count duplicates per doc (top 10)
            placeholders = ",".join(["%s"] * min(len(ids_to_delete), 50000))
            batch = ids_to_delete[:50000]
            cur.execute(
                f"""
                SELECT c.doc_id, d.map_title, COUNT(*) as dupes
                FROM {table} c
                LEFT JOIN docs_{data_source} d ON c.doc_id = d.doc_id
                WHERE c.chunk_id IN ({placeholders})
                GROUP BY c.doc_id, d.map_title
                ORDER BY dupes DESC
                LIMIT 10
            """,
                batch,
            )
            top_docs = cur.fetchall()

    if top_docs:
        print("\n  Top affected documents:")
        print(f"  {'Doc ID':<40} {'Dupes':>6}  Title")
        print(f"  {'-' * 65}")
        for doc_id, title, dupes in top_docs:
            title_short = (title or "?")[:40]
            print(f"  {doc_id:<40} {dupes:>6}  {title_short}")

    if not confirm:
        print(f"\n  DRY RUN -- use --confirm to delete {dupe_count:,} duplicates.")
        return dupe_count

    # ── 3. Delete from Postgres ───────────────────────────────────────────
    print(f"\n  Deleting {dupe_count:,} duplicates from Postgres ...")
    batch_size = 5000
    pg_deleted = 0
    t0 = time.time()

    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(ids_to_delete), batch_size):
                batch = ids_to_delete[i : i + batch_size]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"DELETE FROM {table} WHERE chunk_id IN ({placeholders})",
                    batch,
                )
                pg_deleted += cur.rowcount
                if pg_deleted % 10000 < batch_size:
                    print(f"    Postgres: {pg_deleted:,}/{dupe_count:,} deleted ...")
        conn.commit()

    pg_elapsed = time.time() - t0
    print(f"  Postgres: deleted {pg_deleted:,} chunks in {pg_elapsed:.1f}s")

    # ── 4. Delete from Qdrant ─────────────────────────────────────────────
    print(f"\n  Deleting {dupe_count:,} duplicates from Qdrant ...")
    db = get_db(data_source)
    qdrant_deleted = 0
    t0 = time.time()

    for i in range(0, len(ids_to_delete), batch_size):
        batch = ids_to_delete[i : i + batch_size]
        try:
            db.client.delete(
                collection_name=db.chunks_collection,
                points_selector=batch,
                wait=True,
            )
            qdrant_deleted += len(batch)
        except Exception as e:
            print(f"    Qdrant batch error at offset {i}: {e}")
        if qdrant_deleted % 10000 < batch_size:
            print(f"    Qdrant: {qdrant_deleted:,}/{dupe_count:,} deleted ...")

    qdrant_elapsed = time.time() - t0
    print(f"  Qdrant: deleted {qdrant_deleted:,} chunks in {qdrant_elapsed:.1f}s")

    # ── 5. Verify ─────────────────────────────────────────────────────────
    print("\n  Verifying ...")
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            total_after = cur.fetchone()[0]

    qdrant_after = db.client.count(collection_name=db.chunks_collection).count

    print(f"  Postgres chunks: {total_before:,} -> {total_after:,}")
    print(f"  Qdrant chunks:   {qdrant_after:,}")
    print(f"  Removed: {total_before - total_after:,}")

    return dupe_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix duplicate chunks in PostgreSQL and Qdrant"
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Data source (e.g. uneg, worldbank). Default: all.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete duplicates (default is dry-run).",
    )
    args = parser.parse_args()

    sources = [args.source] if args.source else ["uneg"]
    grand_total = 0

    for src in sources:
        try:
            grand_total += fix_duplicates(src, confirm=args.confirm)
        except Exception as e:
            print(f"Error processing {src}: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 70}")
    action = "Deleted" if args.confirm else "Found"
    print(f"  {action} {grand_total:,} total duplicate chunks.")
    print(f"{'=' * 70}\n")
