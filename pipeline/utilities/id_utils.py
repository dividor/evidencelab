"""
Common utility functions for ID generation used across the pipeline.
"""

import uuid


def generate_doc_id(identifier: str) -> str:
    """Generate a deterministic UUID from a unique string (URL or Filepath)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identifier))
