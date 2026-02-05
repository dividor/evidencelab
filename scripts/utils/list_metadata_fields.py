#!/usr/bin/env python3
"""
Script to query Qdrant and list all metadata fields available in the database.
Shows both the documents and chunks collections with sample values.
"""
import logging
import sys
from collections import Counter, defaultdict
from typing import Any, Dict

from pipeline.db import CHUNKS_COLLECTION, DOCUMENTS_COLLECTION, get_default_db

# Add parent directory to path for imports


db = get_default_db()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyze_collection(collection_name: str, sample_size: int = 100) -> Dict[str, Any]:
    """
    Analyze a collection to find all metadata fields and their types.

    Args:
        collection_name: Name of the collection to analyze
        sample_size: Number of documents to sample

    Returns:
        Dictionary with field information
    """
    logger.info("Analyzing collection: {collection_name}")

    # Get collection count
    try:
        count_result = db.client.count(collection_name=collection_name)
        total_count = count_result.count
    except Exception:
        logger.warning("Could not get collection count: {e}")
        total_count = "unknown"

    # Get sample documents
    results, _ = db.client.scroll(
        collection_name=collection_name,
        limit=sample_size,
        with_payload=True,
    )

    if not results:
        logger.warning("No documents found in {collection_name}")
        return {"collection_name": collection_name, "total_count": 0, "fields": {}}

    # Analyze fields
    field_info: Dict[str, Dict[str, Any]] = defaultdict(  # type: ignore
        lambda: {"count": 0, "types": Counter(), "sample_values": []}
    )

    for point in results:
        payload = point.payload
        for key, value in payload.items():
            field_info[key]["count"] += 1
            field_info[key]["types"][type(value).__name__] += 1

            # Store up to 3 sample values
            if len(field_info[key]["sample_values"]) < 3:
                # Truncate long values
                if isinstance(value, str) and len(value) > 100:
                    sample_value = value[:100] + "..."
                elif isinstance(value, list) and len(value) > 3:
                    sample_value = value[:3] + ["..."]  # type: ignore[assignment]
                else:
                    sample_value = value
                field_info[key]["sample_values"].append(sample_value)

    return {
        "collection_name": collection_name,
        "total_count": total_count,
        "sampled_count": len(results),
        "fields": dict(field_info),
    }


def print_collection_info(collection_data: Dict[str, Any]):
    """Pretty print collection metadata information."""
    print("\n" + "=" * 80)
    print("COLLECTION: {collection_data['collection_name']}")
    print("=" * 80)
    print("Total documents: {collection_data['total_count']:,}")
    print("Sampled documents: {collection_data.get('sampled_count', 0):,}")
    print("Number of unique fields: {len(collection_data['fields'])}")
    print("\n" + "-" * 80)
    print("METADATA FIELDS:")
    print("-" * 80)

    if not collection_data["fields"]:
        print("  (No fields found)")
        return

    # Sort fields alphabetically
    for field_name in sorted(collection_data["fields"].keys()):
        field_data = collection_data["fields"][field_name]

        # Get most common type
        most_common_type = field_data["types"].most_common(1)[0][0]
        type_str = most_common_type

        # Show if multiple types exist
        if len(field_data["types"]) > 1:
            type_str += " ({len(field_data['types'])} types)"

        # Calculate percentage of documents with this field
        sampled_count = collection_data.get("sampled_count", 1)

        print(f"\n  {field_name}")
        print(f"    Type: {type_str}")
        print(
            f"    Present in: {field_data['count']}/{sampled_count} documents "
            f"({(field_data['count'] / sampled_count) * 100:.1f}%)"
        )

        # Show sample values
        if field_data["sample_values"]:
            print("    Sample values:")
            for i, sample in enumerate(field_data["sample_values"], 1):
                # Format the sample value
                if isinstance(sample, str):
                    sample_str = f'"{sample}"'
                elif isinstance(sample, list):
                    sample_str = f"[{', '.join(repr(x) for x in sample)}]"
                else:
                    sample_str = repr(sample)
                print(f"      {i}. {sample_str}")


def main():
    """Main function to analyze all collections."""
    try:
        # Get all collections
        collections_response = db.client.get_collections()
        collection_names = [c.name for c in collections_response.collections]

        print("\n" + "=" * 80)
        print("QDRANT DATABASE METADATA ANALYSIS")
        print("=" * 80)
        print("Connected to Qdrant")
        print("Available collections: {', '.join(collection_names)}")

        # Analyze each collection
        for collection_name in collection_names:
            collection_data = analyze_collection(collection_name, sample_size=100)
            print_collection_info(collection_data)

        # Summary of indexed fields
        print("\n" + "=" * 80)
        print("INDEXED FIELDS (for filtering/faceting)")
        print("=" * 80)

        for collection_name in [DOCUMENTS_COLLECTION, CHUNKS_COLLECTION]:
            if collection_name in collection_names:
                print("\n{collection_name}:")
                print(
                    "  (Indexed fields available, but skipping detailed query due to version compatibility)"  # noqa: E501
                )

        print("\n" + "=" * 80)
        print("ANALYSIS COMPLETE")
        print("=" * 80)

    except Exception:
        logger.error("Error analyzing database: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
