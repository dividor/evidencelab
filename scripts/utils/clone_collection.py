#!/usr/bin/env python3
"""
Clone a Qdrant collection to test different settings.
Useful for experimenting with on_disk, quantization, HNSW parameters, etc.
"""
import argparse
import logging
import sys
from typing import Optional

from dotenv import load_dotenv
from qdrant_client.http import models

from pipeline.db import VECTOR_DISTANCE_METRIC

# Add parent directory to path


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


def clone_collection(
    source_name: str,
    target_name: str,
    on_disk: Optional[bool] = None,
    hnsw_on_disk: Optional[bool] = None,
    enable_quantization: Optional[bool] = None,
    quantization_type: str = "int8",
    hnsw_m: Optional[int] = None,
    hnsw_ef_construct: Optional[int] = None,
    batch_size: int = 100,
    dry_run: bool = False,
):
    """
    Clone a Qdrant collection with optional different settings.

    Args:
        source_name: Source collection name
        target_name: Target collection name
        on_disk: Store vectors on disk (None = copy from source)
        hnsw_on_disk: Store HNSW index on disk (None = copy from source)
        enable_quantization: Enable quantization (None = copy from source)
        quantization_type: int8 or binary
        hnsw_m: HNSW M parameter (None = copy from source)
        hnsw_ef_construct: HNSW ef_construct (None = copy from source)
        batch_size: Number of points to copy per batch
        dry_run: Print plan without executing
    """
    # Connect to Qdrant
    # Connect to Qdrant via shared Database class for robust configuration handling
    from pipeline.db import Database

    try:
        db = Database()
        client = db.client
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        return False

    # Check source collection exists
    try:
        source_info = client.get_collection(source_name)
    except Exception as e:
        logger.error(f"Source collection '{source_name}' not found: {e}")
        return False

    logger.info(f"📊 Source collection: {source_name}")
    logger.info(f"   Vectors: {source_info.vectors_count}")
    logger.info(f"   Points: {source_info.points_count}")

    # Check if target already exists
    existing_collections = {c.name for c in client.get_collections().collections}
    if target_name in existing_collections:
        logger.error(f"Target collection '{target_name}' already exists!")
        logger.info(f"Delete it first: qdrant-client delete-collection {target_name}")
        return False

    # Get source config
    source_config = source_info.config

    # Build target vector config
    distance_metric = getattr(models.Distance, VECTOR_DISTANCE_METRIC)

    # Extract source settings or use overrides
    source_vectors = source_config.params.vectors
    if isinstance(source_vectors, dict):
        # Named vectors (e.g., "dense", "sparse")
        vector_configs = {}
        for name, params in source_vectors.items():
            # Build HNSW config
            hnsw_config = models.HnswConfigDiff(
                m=(
                    hnsw_m
                    if hnsw_m is not None
                    else (params.hnsw_config.m if params.hnsw_config else 16)
                ),
                ef_construct=(
                    hnsw_ef_construct
                    if hnsw_ef_construct is not None
                    else (
                        params.hnsw_config.ef_construct if params.hnsw_config else 100
                    )
                ),
                on_disk=(
                    hnsw_on_disk
                    if hnsw_on_disk is not None
                    else (params.hnsw_config.on_disk if params.hnsw_config else False)
                ),
            )

            # Build vector params
            if name == "dense":
                vector_configs[name] = models.VectorParams(
                    size=params.size,
                    distance=distance_metric,
                    on_disk=(
                        on_disk if on_disk is not None else (params.on_disk or False)
                    ),
                    hnsw_config=hnsw_config,
                )
            else:
                # Sparse or other vectors
                vector_configs[name] = models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
    else:
        # Single unnamed vector
        hnsw_config = models.HnswConfigDiff(
            m=hnsw_m if hnsw_m is not None else 16,
            ef_construct=hnsw_ef_construct if hnsw_ef_construct is not None else 100,
            on_disk=hnsw_on_disk if hnsw_on_disk is not None else False,
        )

        vector_configs = models.VectorParams(
            size=source_vectors.size,
            distance=distance_metric,
            on_disk=on_disk if on_disk is not None else False,
            hnsw_config=hnsw_config,
        )

    # Build collection config
    collection_config = {
        "collection_name": target_name,
        "vectors_config": vector_configs,
    }

    # Add quantization if requested
    if enable_quantization:
        if quantization_type == "int8":
            collection_config["quantization_config"] = models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8,
                    quantile=0.99,
                    always_ram=True,
                )
            )
        elif quantization_type == "binary":
            collection_config["quantization_config"] = models.BinaryQuantization(
                binary=models.BinaryQuantizationConfig(always_ram=True)
            )

    logger.info(f"\n🎯 Target collection: {target_name}")
    logger.info(f"   on_disk: {on_disk if on_disk is not None else 'same as source'}")
    logger.info(
        f"   hnsw_on_disk: {hnsw_on_disk if hnsw_on_disk is not None else 'same as source'}"
    )
    logger.info(
        f"   quantization: {quantization_type if enable_quantization else 'disabled'}"
    )
    if hnsw_m is not None:
        logger.info(f"   hnsw_m: {hnsw_m}")
    if hnsw_ef_construct is not None:
        logger.info(f"   hnsw_ef_construct: {hnsw_ef_construct}")

    if dry_run:
        logger.info("\n🔍 Dry run - no changes made")
        return True

    # Create target collection
    logger.info("\n📦 Creating target collection...")
    client.create_collection(**collection_config)
    logger.info("✓ Collection created")

    # Copy points in batches
    logger.info(f"\n📋 Copying {source_info.points_count} points...")
    offset = None
    total_copied = 0

    while True:
        # Scroll through source collection
        points, next_offset = client.scroll(
            collection_name=source_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        if not points:
            break

        # Upload to target
        client.upsert(
            collection_name=target_name,
            points=points,
        )

        total_copied += len(points)
        logger.info(f"   Copied {total_copied}/{source_info.points_count} points...")

        if next_offset is None:
            break
        offset = next_offset

    logger.info(f"\n✅ Successfully cloned {total_copied} points!")
    logger.info("\n💡 To use the new collection, set in your .env:")
    logger.info("   CHUNKS_COLLECTION=%s", target_name)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Clone a Qdrant collection with optional different settings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clone with vectors on disk
  python scripts/clone_collection.py chunks chunks_ondisk --on-disk

  # Clone with quantization enabled
  python scripts/clone_collection.py chunks chunks_quantized --quantization --quantization-type int8

  # Clone with custom HNSW settings
  python scripts/clone_collection.py chunks chunks_hnsw32 --hnsw-m 32 --hnsw-ef-construct 200

  # Dry run to see what would happen
  python scripts/clone_collection.py chunks chunks_test --on-disk --dry-run
        """,
    )

    parser.add_argument("source", help="Source collection name")
    parser.add_argument("target", help="Target collection name")

    # Storage options
    parser.add_argument("--on-disk", action="store_true", help="Store vectors on disk")
    parser.add_argument(
        "--hnsw-on-disk", action="store_true", help="Store HNSW index on disk"
    )

    # Quantization options
    parser.add_argument(
        "--quantization", action="store_true", help="Enable quantization"
    )
    parser.add_argument(
        "--quantization-type",
        choices=["int8", "binary"],
        default="int8",
        help="Quantization type (default: int8)",
    )

    # HNSW options
    parser.add_argument("--hnsw-m", type=int, help="HNSW M parameter (edges per node)")
    parser.add_argument(
        "--hnsw-ef-construct", type=int, help="HNSW ef_construct parameter"
    )

    # Other options
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Batch size for copying"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print plan without executing"
    )

    args = parser.parse_args()

    success = clone_collection(
        source_name=args.source,
        target_name=args.target,
        on_disk=args.on_disk or None,
        hnsw_on_disk=args.hnsw_on_disk or None,
        enable_quantization=args.quantization,
        quantization_type=args.quantization_type,
        hnsw_m=args.hnsw_m,
        hnsw_ef_construct=args.hnsw_ef_construct,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
