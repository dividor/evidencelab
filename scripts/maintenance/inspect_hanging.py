import os
import sys

# Add repo root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

from pipeline.db import get_db  # noqa: E402


def inspect():
    try:
        db = get_db("uneg")
        # Check target docs
        # target_ids = ['b0eaade7-79e3-52e0-9208-a580f71785b2']

        # Check for hanging docs
        print("\n--- Searching for hanging docs ---")
        query = (
            "SELECT doc_id, sys_status, sys_data->'sys_stages' "
            "FROM docs_uneg "
            "WHERE sys_status IN ('indexing', 'summarizing', 'pending')"
        )
        with db.pg._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                print(f"Found {len(rows)} potentially hanging docs")
                for r in rows[:5]:
                    print(r)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    inspect()
