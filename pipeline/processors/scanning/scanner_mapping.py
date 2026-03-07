"""Field mapping helpers for ScanProcessor."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pipeline.db import get_field_mapping
from pipeline.processors.scanning.mapping_utils import sanitize_source_key

logger = logging.getLogger(__name__)

# Pattern for transform functions, e.g. YEAR(docdt)
_TRANSFORM_RE = re.compile(r"^([A-Z_]+)\((.+)\)$")


class ScannerMappingMixin:
    """Mixin for ScanProcessor field mapping logic."""

    db: Any

    def _apply_field_mapping(
        self, metadata: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_metadata = metadata.copy()
        field_mapping = get_field_mapping(self.db.data_source)
        logger.info("Field mapping for %s: %s", self.db.data_source, field_mapping)
        if not field_mapping:
            return self._build_src_fields(raw_metadata), {}

        mapped_core, fixed_value_fields = self._apply_fixed_values(field_mapping)
        mapped_core.update(
            self._apply_mapped_core_values(
                raw_metadata, field_mapping, fixed_value_fields
            )
        )
        src_fields = self._build_src_fields(raw_metadata)
        map_fields = self._build_map_fields(mapped_core)

        org_value = mapped_core.get("organization", "MISSING")
        logger.info("Final mapped organization: %s", org_value)
        return src_fields, map_fields

    # Fields that should never be split into lists (URLs, titles, years).
    _SCALAR_FIELDS = frozenset(
        {"title", "published_year", "year", "pdf_url", "report_url", "organization"}
    )

    @staticmethod
    def _resolve_source_value(
        raw_metadata: Dict[str, Any], mapping_value: str
    ) -> Optional[Any]:
        """Resolve a mapping value to the raw source value.

        Supports:
        - Plain field names: ``"display_title"``
        - Transform functions: ``"YEAR(docdt)"``
        """
        match = _TRANSFORM_RE.match(mapping_value)
        if not match:
            return raw_metadata.get(mapping_value)

        func_name, field_name = match.group(1), match.group(2)
        raw_value = raw_metadata.get(field_name)
        if raw_value is None or raw_value == "":
            return None

        if func_name == "YEAR":
            try:
                # Handle trailing Z (UTC indicator) for fromisoformat
                val_str = str(raw_value).replace("Z", "+00:00")
                return str(datetime.fromisoformat(val_str).year)
            except (ValueError, TypeError):
                logger.warning(
                    "YEAR transform failed for field '%s' value '%s'",
                    field_name,
                    raw_value,
                )
                return None

        logger.warning("Unknown transform function: %s", func_name)
        return None

    def _apply_mapped_core_values(
        self,
        raw_metadata: Dict[str, Any],
        field_mapping: Dict[str, Any],
        fixed_value_fields: set,
    ) -> Dict[str, Any]:
        mapped_core: Dict[str, Any] = {}
        for core_field, mapping_value in field_mapping.items():
            if core_field in fixed_value_fields:
                continue
            if isinstance(mapping_value, str) and mapping_value.startswith(
                "fixed_value:"
            ):
                continue
            source_value = self._resolve_source_value(raw_metadata, mapping_value)
            if source_value is None or source_value == "":
                continue
            if core_field in ("published_year", "year"):
                mapped_core[core_field] = str(source_value)
            else:
                mapped_core[core_field] = self._split_if_multival(
                    core_field, source_value
                )
        return mapped_core

    @classmethod
    def _split_if_multival(cls, core_field: str, value: Any) -> Any:
        """Split semicolon-separated strings into lists for multi-value fields."""
        if core_field in cls._SCALAR_FIELDS:
            return value
        if isinstance(value, str) and ";" in value:
            parts = [v.strip() for v in value.split(";") if v.strip()]
            return parts if len(parts) > 1 else (parts[0] if parts else value)
        return value

    def _build_src_fields(self, raw_metadata: Dict[str, Any]) -> Dict[str, Any]:
        src_fields: Dict[str, Any] = {}
        for key, value in raw_metadata.items():
            sanitized = sanitize_source_key(str(key))
            if not sanitized:
                continue
            if sanitized in {
                "download_error",
                "chunk_count",
                "id",
                "pipeline_elapsed_seconds",
            }:
                continue
            src_fields[f"src_{sanitized}"] = value
        return src_fields

    @staticmethod
    def _build_map_fields(mapped_core: Dict[str, Any]) -> Dict[str, Any]:
        return {f"map_{key}": value for key, value in mapped_core.items()}

    def _apply_fixed_values(
        self, field_mapping: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], set]:
        transformed_metadata: Dict[str, Any] = {}
        fixed_value_fields = set()
        for core_field, mapping_value in field_mapping.items():
            if isinstance(mapping_value, str) and mapping_value.startswith(
                "fixed_value:"
            ):
                fixed_value = mapping_value[len("fixed_value:") :].strip()
                if fixed_value:
                    fixed_value_fields.add(core_field)
                    transformed_metadata[core_field] = fixed_value
                    logger.info("Set fixed value for %s: %s", core_field, fixed_value)
        return transformed_metadata, fixed_value_fields

    def _build_reverse_mapping(self, field_mapping: Dict[str, Any]) -> Dict[str, str]:
        return {
            v: k
            for k, v in field_mapping.items()
            if not (isinstance(v, str) and v.startswith("fixed_value:"))
        }

    def _transform_metadata_fields(
        self,
        qdrant_metadata: Dict[str, Any],
        reverse_mapping: Dict[str, str],
        transformed_metadata: Dict[str, Any],
        fixed_value_fields: set,
    ) -> None:
        for key, value in qdrant_metadata.items():
            core_field = reverse_mapping.get(key, key)
            if core_field not in fixed_value_fields:
                if core_field not in transformed_metadata:
                    transformed_metadata[core_field] = value
                elif value and value != transformed_metadata.get(core_field):
                    transformed_metadata[core_field] = value
            if key != core_field and key not in transformed_metadata:
                transformed_metadata[key] = value

    def _ensure_fixed_values(
        self, transformed_metadata: Dict[str, Any], field_mapping: Dict[str, Any]
    ) -> None:
        for core_field, mapping_value in field_mapping.items():
            if isinstance(mapping_value, str) and mapping_value.startswith(
                "fixed_value:"
            ):
                fixed_value = mapping_value[len("fixed_value:") :].strip()
                if not fixed_value:
                    continue
                if core_field not in transformed_metadata:
                    transformed_metadata[core_field] = fixed_value
                    logger.warning(
                        "Re-applied missing fixed value for %s: %s",
                        core_field,
                        fixed_value,
                    )
                    continue
                current_value = transformed_metadata[core_field]
                if current_value != fixed_value:
                    logger.warning(
                        "Fixed value for %s was overwritten! Expected: %s, Got: %s",
                        core_field,
                        fixed_value,
                        current_value,
                    )
                    transformed_metadata[core_field] = fixed_value
                    logger.info(
                        "Restored fixed value for %s: %s",
                        core_field,
                        fixed_value,
                    )
