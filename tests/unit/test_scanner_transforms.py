"""Tests for field mapping transform functions (e.g. YEAR) in scanner mapping."""

from pipeline.processors.scanning.scanner_mapping import ScannerMappingMixin


class TestResolveSourceValue:
    """Test _resolve_source_value static method."""

    def test_plain_field_lookup(self):
        meta = {"title": "Hello World"}
        assert ScannerMappingMixin._resolve_source_value(meta, "title") == "Hello World"

    def test_plain_field_missing_returns_none(self):
        assert ScannerMappingMixin._resolve_source_value({}, "title") is None

    def test_year_transform_iso_datetime(self):
        meta = {"docdt": "2020-02-01T05:00:00Z"}
        assert ScannerMappingMixin._resolve_source_value(meta, "YEAR(docdt)") == "2020"

    def test_year_transform_date_only(self):
        meta = {"docdt": "2023-06-15"}
        assert ScannerMappingMixin._resolve_source_value(meta, "YEAR(docdt)") == "2023"

    def test_year_transform_missing_field_returns_none(self):
        assert ScannerMappingMixin._resolve_source_value({}, "YEAR(docdt)") is None

    def test_year_transform_empty_string_returns_none(self):
        meta = {"docdt": ""}
        assert ScannerMappingMixin._resolve_source_value(meta, "YEAR(docdt)") is None

    def test_year_transform_unparseable_returns_none(self):
        meta = {"docdt": "not-a-date"}
        assert ScannerMappingMixin._resolve_source_value(meta, "YEAR(docdt)") is None

    def test_unknown_transform_returns_none(self):
        meta = {"docdt": "2020-01-01"}
        assert ScannerMappingMixin._resolve_source_value(meta, "MONTH(docdt)") is None
