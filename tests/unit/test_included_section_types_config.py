"""The default-included section types come from config.json, shared with Search.

``get_default_included_section_types`` is the single resolver both the admin TOC
Validator service and the offline bulk script use, so their notion of "included"
tracks Search's ``config.application.search.default_included_section_types`` and
cannot drift from it.
"""

from unittest.mock import patch

import pytest

from pipeline.db import config as cfg
from pipeline.validation.section_inclusion import DEFAULT_INCLUDED_SECTION_TYPES

pytestmark = pytest.mark.unit


class TestGetDefaultIncludedSectionTypes:
    def test_reads_and_normalizes_configured_list(self):
        app_cfg = {
            "search": {"default_included_section_types": [" Findings ", "CONTEXT"]}
        }
        with patch.object(cfg, "get_application_config", return_value=app_cfg):
            assert cfg.get_default_included_section_types() == ["findings", "context"]

    def test_falls_back_when_key_absent(self):
        with patch.object(cfg, "get_application_config", return_value={"search": {}}):
            assert cfg.get_default_included_section_types() == list(
                DEFAULT_INCLUDED_SECTION_TYPES
            )

    def test_falls_back_when_list_empty(self):
        app_cfg = {"search": {"default_included_section_types": []}}
        with patch.object(cfg, "get_application_config", return_value=app_cfg):
            assert cfg.get_default_included_section_types() == list(
                DEFAULT_INCLUDED_SECTION_TYPES
            )

    def test_falls_back_when_no_search_section(self):
        with patch.object(cfg, "get_application_config", return_value={}):
            assert cfg.get_default_included_section_types() == list(
                DEFAULT_INCLUDED_SECTION_TYPES
            )
