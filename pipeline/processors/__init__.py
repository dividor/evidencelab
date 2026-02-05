"""
Pipeline processors package.

Provides reusable processor classes for document processing stages.
Each processor:
- Implements the BaseProcessor interface
- Handles one-time model loading in setup()
- Processes documents via process_document()
- Can be used independently or composed by the orchestrator

Usage:
    from pipeline.processors import ParseProcessor, SummarizeProcessor, IndexProcessor

    # Process a single document through multiple stages
    with ParseProcessor() as parser:
        result = parser.process_document(doc)

    # Or manually manage lifecycle
    indexer = IndexProcessor()
    indexer.setup()
    for doc in docs:
        indexer.process_document(doc)
    indexer.teardown()
"""

from pipeline.processors.base import BaseProcessor
from pipeline.processors.indexing.indexer import IndexProcessor
from pipeline.processors.parsing.parser import ParseProcessor
from pipeline.processors.scanning.scanner import ScanProcessor
from pipeline.processors.summarization.summarizer import SummarizeProcessor
from pipeline.processors.tagging.tagger import TaggerProcessor

__all__ = [
    "BaseProcessor",
    "ParseProcessor",
    "SummarizeProcessor",
    "IndexProcessor",
    "ScanProcessor",
    "TaggerProcessor",
]
