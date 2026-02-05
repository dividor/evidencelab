"""Field mapping helpers for ScanProcessor."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from pipeline.db import get_field_mapping
from pipeline.processors.scanning.mapping_utils import sanitize_source_key

logger = logging.getLogger(__name__)


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
            source_value = raw_metadata.get(mapping_value)
            if source_value is None or source_value == "":
                continue
            if core_field in ("published_year", "year"):
                mapped_core[core_field] = str(source_value)
            else:
                mapped_core[core_field] = source_value
        return mapped_core

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
