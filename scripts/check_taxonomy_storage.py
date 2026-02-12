"""Quick script to check what's actually stored in Qdrant documents collection."""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.db import get_db

db = get_db("uneg")

# Get a document that should have taxonomies
from qdrant_client.http import models

results = db.client.scroll(
    collection_name=db.documents_collection,
    limit=5,
    with_payload=True,
    with_vectors=False,
)

print("Checking first 5 documents...")
for point in results[0]:
    doc_id = point.id
    payload = point.payload

    # Check for taxonomy fields
    has_tags = any(key.startswith("tag_") for key in payload.keys())

    if has_tags:
        print(f"\n✓ Document {doc_id} has taxonomy fields:")
        for key in payload.keys():
            if key.startswith("tag_"):
                value = payload[key]
                print(f"  {key}: {value} (type: {type(value).__name__})")
    else:
        print(f"\n✗ Document {doc_id} has NO taxonomy fields")
        print(f"  Available fields: {list(payload.keys())[:10]}")
