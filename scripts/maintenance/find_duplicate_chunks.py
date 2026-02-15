#!/usr/bin/env python3
"""
Find duplicate chunks in both PostgreSQL and Qdrant for the same document.

Checks for chunks that share the same sys_text content within a single doc_id.
Also compares chunk counts between Postgres and Qdrant per document.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402
from pipeline.db.postgres_client import PostgresClient  # noqa: E402


def find_postgres_duplicates(data_source: str, verbose: bool = False):
    """Find duplicate chunks in PostgreSQL (same doc_id + same sys_text)."""
    print(f"\n--- PostgreSQL: chunks_{data_source} ---")

    pg = PostgresClient(data_source)
    table = pg.chunks_table

    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            total = cur.fetchone()[0]
            print(f"Total chunks: {total:,}")

            # Find docs with duplicate chunk text
            cur.execute(
                f"""
                SELECT doc_id, md5(sys_text), COUNT(*) AS cnt
                FROM {table}
                WHERE sys_text IS NOT NULL
                GROUP BY doc_id, md5(sys_text)
                HAVING COUNT(*) > 1
                ORDER BY cnt DESC
            """
            )
            dupes = cur.fetchall()

            if not dupes:
                print("No duplicate chunks found in Postgres.")
                return total, 0

            total_extra = sum(row[2] - 1 for row in dupes)
            unique_docs = len(set(row[0] for row in dupes))

            print(f"Duplicate groups: {len(dupes):,}")
            print(f"Extra (removable) chunks: {total_extra:,}")
            print(f"Affected documents: {unique_docs:,}")

            if verbose:
                print(f"\n{'Doc ID':<50} {'Copies':>6}")
                print("-" * 58)
                for doc_id, _hash, cnt in dupes[:20]:
                    print(f"{doc_id[:49]:<50} {cnt:>6}")
                if len(dupes) > 20:
                    print(f"  ... and {len(dupes) - 20} more groups")

                # Show sample chunk_ids for top duplicates
                print("\nSample duplicate chunk_ids:")
                for doc_id, _hash, cnt in dupes[:3]:
                    cur.execute(
                        f"""
                        SELECT chunk_id, sys_page_num, left(sys_text, 60)
                        FROM {table}
                        WHERE doc_id = %s AND md5(sys_text) = %s
                        ORDER BY chunk_id
                    """,
                        (doc_id, _hash),
                    )
                    rows = cur.fetchall()
                    print(f"\n  doc_id: {doc_id}")
                    for cid, page, text in rows:
                        preview = (text or "").replace("\n", " ")
                        print(f'    {cid}  page={page}  "{preview}..."')

            return total, total_extra


def find_qdrant_duplicates(data_source: str, verbose: bool = False):
    """Find duplicate chunks in Qdrant by scrolling and comparing doc_id + text."""
    print(f"\n--- Qdrant: chunks_{data_source} ---")

    db = get_db(data_source)
    collection = db.chunks_collection

    total = db.client.count(collection_name=collection).count
    print(f"Total chunks: {total:,}")

    # Scroll through all chunks, group by doc_id + text hash
    seen = defaultdict(list)  # (doc_id, text_snippet) -> [point_ids]
    next_offset = None
    loaded = 0

    while True:
        results, next_offset = db.client.scroll(
            collection_name=collection,
            limit=1000,
            offset=next_offset,
            with_payload=["doc_id", "sys_text"],
            with_vectors=False,
        )
        if not results:
            break
        for point in results:
            doc_id = point.payload.get("doc_id", "")
            text = point.payload.get("sys_text", "") or ""
            # Use first 200 chars as key to avoid huge memory usage
            key = (doc_id, hash(text))
            seen[key].append(point.id)
        loaded += len(results)
        if loaded % 10000 == 0:
            print(f"  Scanned {loaded:,}/{total:,} chunks...")
        if next_offset is None:
            break

    print(f"  Scanned {loaded:,} chunks total")

    # Find duplicates
    dupe_groups = {k: v for k, v in seen.items() if len(v) > 1}
    if not dupe_groups:
        print("No duplicate chunks found in Qdrant.")
        return total, 0

    total_extra = sum(len(ids) - 1 for ids in dupe_groups.values())
    unique_docs = len(set(k[0] for k in dupe_groups))

    print(f"Duplicate groups: {len(dupe_groups):,}")
    print(f"Extra (removable) chunks: {total_extra:,}")
    print(f"Affected documents: {unique_docs:,}")

    if verbose:
        print(f"\n{'Doc ID':<50} {'Copies':>6}  Point IDs")
        print("-" * 70)
        for (doc_id, _), ids in sorted(dupe_groups.items(), key=lambda x: -len(x[1]))[
            :20
        ]:
            id_strs = [str(i)[:12] for i in ids[:4]]
            more = f" +{len(ids)-4}" if len(ids) > 4 else ""
            print(f"{doc_id[:49]:<50} {len(ids):>6}  {', '.join(id_strs)}{more}")

    return total, total_extra


def compare_counts(data_source: str):
    """Compare chunk counts per doc between Postgres and Qdrant."""
    print(f"\n--- Count comparison: {data_source} ---")

    pg = PostgresClient(data_source)
    db = get_db(data_source)

    # Postgres counts per doc
    pg_counts = {}
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, COUNT(*) FROM {pg.chunks_table} GROUP BY doc_id"
            )
            for doc_id, cnt in cur.fetchall():
                pg_counts[doc_id] = cnt

    # Qdrant: count chunks per doc via scroll
    qdrant_counts: dict[str, int] = defaultdict(int)
    next_offset = None
    while True:
        results, next_offset = db.client.scroll(
            collection_name=db.chunks_collection,
            limit=1000,
            offset=next_offset,
            with_payload=["doc_id"],
            with_vectors=False,
        )
        if not results:
            break
        for point in results:
            doc_id = point.payload.get("doc_id", "")
            qdrant_counts[doc_id] += 1
        if next_offset is None:
            break

    all_docs = set(pg_counts) | set(qdrant_counts)
    mismatches = []
    for doc_id in all_docs:
        pc = pg_counts.get(doc_id, 0)
        qc = qdrant_counts.get(doc_id, 0)
        if pc != qc:
            mismatches.append((doc_id, pc, qc))

    if not mismatches:
        print(f"All {len(all_docs):,} documents have matching chunk counts.")
    else:
        mismatches.sort(key=lambda x: abs(x[1] - x[2]), reverse=True)
        print(f"Mismatched documents: {len(mismatches):,} / {len(all_docs):,}")
        print(f"\n{'Doc ID':<50} {'PG':>6} {'Qdrant':>6} {'Diff':>6}")
        print("-" * 70)
        for doc_id, pc, qc in mismatches[:20]:
            print(f"{doc_id[:49]:<50} {pc:>6} {qc:>6} {qc-pc:>+6}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")

    return len(mismatches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find duplicate chunks in PostgreSQL and Qdrant"
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Data source (e.g. uneg, worldbank). Default: all sources.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show sample duplicate details",
    )
    parser.add_argument(
        "--skip-qdrant",
        action="store_true",
        help="Only check PostgreSQL, skip Qdrant scan",
    )
    args = parser.parse_args()

    sources = [args.source] if args.source else ["uneg", "worldbank"]

    for src in sources:
        print(f"\n{'=' * 70}")
        print(f"  Data source: {src}")
        print(f"{'=' * 70}")

        try:
            pg_total, pg_dupes = find_postgres_duplicates(src, verbose=args.verbose)
        except Exception as e:
            print(f"Postgres error for {src}: {e}")
            pg_total, pg_dupes = 0, 0

        if not args.skip_qdrant:
            try:
                q_total, q_dupes = find_qdrant_duplicates(src, verbose=args.verbose)
            except Exception as e:
                print(f"Qdrant error for {src}: {e}")
                q_total, q_dupes = 0, 0

            try:
                compare_counts(src)
            except Exception as e:
                print(f"Comparison error for {src}: {e}")

        print(f"\nSummary for {src}:")
        print(f"  Postgres: {pg_total:,} total, {pg_dupes:,} duplicate")
        if not args.skip_qdrant:
            print(f"  Qdrant:   {q_total:,} total, {q_dupes:,} duplicate")

    print()
