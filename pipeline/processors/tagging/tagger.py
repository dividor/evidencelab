"""Facade for tagger implementations."""

from pipeline.processors.tagging import tagger_core
from pipeline.processors.tagging.tagger_core import (
    SECTION_TYPES,
    BaseTagger,
    SectionTypeTagger,
    TaggerProcessor,
    add_passage_prefix,
    add_query_prefix,
    cosine_similarity,
    is_e5_model,
    main,
)

__all__ = [
    "BaseTagger",
    "SECTION_TYPES",
    "SectionTypeTagger",
    "TaggerProcessor",
    "add_passage_prefix",
    "add_query_prefix",
    "cosine_similarity",
    "is_e5_model",
    "main",
]

if __name__ == "__main__":
    tagger_core.main()
