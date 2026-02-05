"""Facade for tagger implementations."""

from pipeline.processors.tagging.tagger_base import BaseTagger
from pipeline.processors.tagging.tagger_cli import main
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES
from pipeline.processors.tagging.tagger_helpers import (
    add_passage_prefix,
    add_query_prefix,
    cosine_similarity,
    is_e5_model,
)
from pipeline.processors.tagging.tagger_processor import TaggerProcessor
from pipeline.processors.tagging.tagger_section_type import SectionTypeTagger

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
