"""
base.py - Abstract base class for all pipeline processors.

This provides a consistent interface for document processing stages.
Each processor can be used independently or composed by the orchestrator.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pipeline.db import make_stage, update_stages

logger = logging.getLogger(__name__)


class BaseProcessor(ABC):
    """
    Abstract base class for pipeline processors.

    All processors must implement:
    - name: Human-readable name for logging
    - stage_name: Stage identifier for tracking (download, parse, summarize, tag, index)
    - process_document(doc): Process a single document

    Optionally can implement:
    - setup(): One-time initialization (load models, etc.)
    - teardown(): Cleanup resources
    """

    name: str = "BaseProcessor"
    stage_name: str = (
        "unknown"  # Override in subclasses: download, parse, summarize, tag, index
    )

    def __init__(self):
        """Initialize the processor."""
        self._initialized = False

    def setup(self) -> None:
        """
        One-time initialization. Override to load models, connect to services, etc.

        Called automatically before first process_document() call if not already done.
        """
        self._initialized = True
        logger.info("✓ %s initialized", self.name)

    def teardown(self) -> None:
        """
        Cleanup resources. Override to close connections, release memory, etc.
        """
        self._initialized = False
        logger.info("✓ %s teardown complete", self.name)

    def ensure_setup(self) -> None:
        """Ensure setup() has been called."""
        if not self._initialized:
            self.setup()

    @abstractmethod
    def process_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single document.

        Args:
            doc: Document dictionary with at minimum:
                - id: Document ID
                - filepath: Path to source file
                - status: Current status (downloaded, parsed, summarized, etc.)

        Returns:
            Dict with:
                - success: bool
                - updates: Dict of fields to update in database (includes 'stages')
                - error: Optional error message
        """
        raise NotImplementedError("Subclasses must implement process_document()")

    def build_stage_updates(
        self,
        doc: Dict[str, Any],
        success: bool,
        error: Optional[str] = None,
        **metadata,
    ) -> Dict[str, Any]:
        """
        Build the stages update dict for this processor's stage.

        Args:
            doc: Document with existing 'stages' field (or None)
            success: Whether the stage succeeded
            error: Error message if failed
            **metadata: Stage-specific metadata (page_count, method, etc.)

        Returns:
            Dict with 'stages' field containing updated stages
        """
        existing_stages = self._get_existing_stages(doc)
        stage_info = make_stage(success, error, **metadata)
        updated_stages = update_stages(existing_stages, self.stage_name, stage_info)
        return {"sys_stages": updated_stages}

    @staticmethod
    def _get_existing_stages(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing_stages = doc.get("sys_stages")
        if existing_stages is None:
            sys_data = doc.get("sys_data")
            if isinstance(sys_data, dict):
                existing_stages = sys_data.get("sys_stages")
        if isinstance(existing_stages, str):
            try:
                existing_stages = json.loads(existing_stages)
            except Exception:
                existing_stages = None
        return existing_stages

    def __enter__(self):
        """Context manager entry."""
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.teardown()
        return False
