"""Base tagger abstractions."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from fastembed import TextEmbedding


class BaseTagger(ABC):
    """Abstract base class for chunk taggers."""

    name: str = "BaseTagger"
    tag_field: str = "tag"

    def __init__(self, embedding_model: Optional[TextEmbedding] = None):
        self._embedding_model = embedding_model

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
