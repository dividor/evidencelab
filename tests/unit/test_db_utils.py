import pytest

import pipeline.db as db
from pipeline.db import (
    _clean_model_name,
    core_to_source_field,
    get_application_config,
    get_filter_fields,
    load_datasources_config,
    source_to_core_field,
)


def test_clean_model_name_normalizes():
    assert (
        _clean_model_name("intfloat/multilingual-e5-large") == "multilingual_e5_large"
    )
    assert _clean_model_name("foo.bar-v2") == "foo_bar"


def _find_datasource_with_mapping(config, key: str):
    datasources = config.get("datasources", config)
    for source_config in datasources.values():
        if not isinstance(source_config, dict):
            continue
        mapping = source_config.get("field_mapping", {})
        if key in mapping:
            return source_config["data_subdir"], mapping
    raise AssertionError(f"No datasource found with field mapping for '{key}'")


def _find_fixed_value_mapping(config):
    datasources = config.get("datasources", config)
    for source_config in datasources.values():
        if not isinstance(source_config, dict):
            continue
        mapping = source_config.get("field_mapping", {})
        for field, value in mapping.items():
            if isinstance(value, str) and value.startswith("fixed_value:"):
                return source_config["data_subdir"], field
    raise AssertionError("No fixed_value mapping found in datasource config")


@pytest.fixture()
def configured_datasources(monkeypatch):
    config = {
        "datasources": {
            "Test Source": {
                "data_subdir": "test",
                "field_mapping": {
                    "organization": "agency",
                    "title": "title",
                    "organization_fixed": "fixed_value:Org",
                },
                "filter_fields": {"organization": "Organization"},
            }
        },
        "application": {"search": {"default_dense_model": "e5_large"}},
    }
    monkeypatch.setattr(db, "_datasources_config", config, raising=False)
    return config


def test_field_mapping_for_configured_source(configured_datasources):
    config = load_datasources_config()
    data_subdir, mapping = _find_datasource_with_mapping(config, "organization")
    assert mapping["organization"]

    filters = get_filter_fields(data_subdir)
    assert "organization" in filters


def test_core_and_source_field_translation(configured_datasources):
    config = load_datasources_config()
    data_subdir, mapping = _find_datasource_with_mapping(config, "organization")
    source_field = mapping["organization"]

    assert core_to_source_field(data_subdir, "organization") == source_field
    assert source_to_core_field(data_subdir, source_field) == "organization"

    fixed_data_subdir, fixed_field = _find_fixed_value_mapping(config)
    assert core_to_source_field(fixed_data_subdir, fixed_field) == fixed_field


def test_application_config_exists(configured_datasources):
    config = load_datasources_config()
    assert isinstance(config, dict)

    app_config = get_application_config()
    assert isinstance(app_config, dict)
