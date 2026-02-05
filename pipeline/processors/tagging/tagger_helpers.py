"""Helper utilities for tagger module."""

import numpy as np


def is_e5_model(model_name: str) -> bool:
    """Return True if model name indicates E5."""
    return "e5" in str(model_name).lower()


def add_query_prefix(text: str, model_name: str) -> str:
    """Add 'query: ' prefix for E5 models during search."""
    if is_e5_model(model_name):
        return f"query: {text}"
    return text


def add_passage_prefix(text: str, model_name: str) -> str:
    """Add 'passage: ' prefix for E5 models during indexing."""
    if is_e5_model(model_name):
        return f"passage: {text}"
    return text


def cosine_similarity(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(
        np.dot(vector_a, vector_b)
        / (np.linalg.norm(vector_a) * np.linalg.norm(vector_b))
    )
