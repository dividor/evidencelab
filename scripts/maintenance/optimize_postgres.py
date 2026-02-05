import os
import sys

# Add parent directory to path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from pipeline.db.postgres_client import PostgresClient  # noqa: E402


def optimize_postgres(data_source: str = "uneg"):
    print(f"Optimizing Postgres tables for data source: {data_source}...")
    pg = PostgresClient(data_source)

    # 1. Ensure Indexes
    print("Ensuring indexes...")
    pg.ensure_sidecar_tables()  # This now includes index creation

    # 2. Backfill sys_status and sys_status_timestamp
    print("Backfilling sys_status and sys_status_timestamp...")
    with pg._get_conn() as conn:
        with conn.cursor() as cur:
            # Backfill sys_status
            cur.execute(
                f"""
                UPDATE {pg.docs_table}
                SET sys_status = sys_data ->> 'sys_status'
                WHERE sys_status IS NULL AND sys_data ? 'sys_status';
            """
            )
            print(f"Updated {cur.rowcount} rows for sys_status.")

            # Backfill sys_status_timestamp
            cur.execute(
                f"""
                UPDATE {pg.docs_table}
                SET sys_status_timestamp = (
                    CASE
                        WHEN sys_data ->> 'sys_status_timestamp' IS NOT NULL
                        THEN (sys_data ->> 'sys_status_timestamp')::timestamptz
                        ELSE NULL
                    END
                )
                WHERE sys_status_timestamp IS NULL AND sys_data ? 'sys_status_timestamp';
            """
            )
            print(f"Updated {cur.rowcount} rows for sys_status_timestamp.")

            # Ensure sys_file_format column
            cur.execute(
                f"ALTER TABLE {pg.docs_table} ADD COLUMN IF NOT EXISTS sys_file_format TEXT"
            )

            # Backfill sys_file_format
            cur.execute(
                f"""
                UPDATE {pg.docs_table}
                SET sys_file_format = sys_data ->> 'sys_file_format'
                WHERE sys_file_format IS NULL AND sys_data ? 'sys_file_format';
            """
            )
            print(f"Updated {cur.rowcount} rows for sys_file_format.")

        conn.commit()

    # 3. Analyze
    print("Running ANALYZE...")
    with pg._get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"ANALYZE {pg.docs_table}")
        conn.autocommit = (
            False  # Restore if needed, though ctx manager normally handles transaction
        )

    print("Optimization complete.")


if __name__ == "__main__":
    sources = ["uneg", "gcf", "world bank"]  # Add other sources as needed or make arg
    if len(sys.argv) > 1:
        sources = [sys.argv[1]]

    for source in sources:
        try:
            optimize_postgres(source)
        except Exception as e:
            print(f"Error optimizing {source}: {e}")
