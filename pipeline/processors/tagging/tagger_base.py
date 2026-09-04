"""Base tagger abstractions."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from fastembed import TextEmbedding

from pipeline.utilities.usage_recorder import UsageCollector


class BaseTagger(ABC):
    """Abstract base class for chunk taggers."""

    name: str = "BaseTagger"
    tag_field: str = "tag"

    def __init__(self, embedding_model: Optional[TextEmbedding] = None):
        self._embedding_model = embedding_model
        # Shared per-document token-usage accumulator, injected by the
        # TaggerProcessor so all sub-taggers' LLM calls are cost-tracked.
        self.usage_collector: Optional[UsageCollector] = None

    def set_usage_collector(self, collector: Optional[UsageCollector]) -> None:
        """Attach the processor's shared token-usage accumulator."""
        self.usage_collector = collector

    @abstractmethod
    def setup(self) -> None:
        """Initialize tagger resources."""
        raise NotImplementedError

    @abstractmethod
    def tag_chunk(
        self, chunk: Dict[str, Any], document: Dict[str, Any]
    ) -> Optional[Any]:
        """Tag a chunk and return the tag or None."""
        raise NotImplementedError
