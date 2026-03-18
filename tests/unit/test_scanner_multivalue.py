"""Tests for multi-value field splitting in scanner mapping."""

from pipeline.processors.scanning.scanner_mapping import ScannerMappingMixin


class TestSplitIfMultival:
    """Test _split_if_multival class method."""

    def test_single_value_unchanged(self):
        assert ScannerMappingMixin._split_if_multival("country", "Kenya") == "Kenya"

    def test_semicolon_splits_into_list(self):
        result = ScannerMappingMixin._split_if_multival(
            "country", "Ethiopia; Kenya; Rwanda"
        )
        assert result == ["Ethiopia", "Kenya", "Rwanda"]

    def test_strips_whitespace(self):
        result = ScannerMappingMixin._split_if_multival(
            "country", "  Ethiopia ;  Kenya  ; Rwanda  "
        )
        assert result == ["Ethiopia", "Kenya", "Rwanda"]

    def test_single_item_after_split_returns_string(self):
        result = ScannerMappingMixin._split_if_multival("country", "Kenya;")
        assert result == "Kenya"

    def test_empty_parts_filtered(self):
        result = ScannerMappingMixin._split_if_multival("country", "Ethiopia;; ;Kenya")
        assert result == ["Ethiopia", "Kenya"]

    def test_scalar_field_not_split(self):
        result = ScannerMappingMixin._split_if_multival("title", "Part A; Part B")
        assert result == "Part A; Part B"

    def test_published_year_not_split(self):
        result = ScannerMappingMixin._split_if_multival("published_year", "2023; 2024")
        assert result == "2023; 2024"

    def test_pdf_url_not_split(self):
        url = "https://example.com/a;b"
        assert ScannerMappingMixin._split_if_multival("pdf_url", url) == url

    def test_organization_not_split(self):
        assert (
            ScannerMappingMixin._split_if_multival("organization", "WFP; UNICEF")
            == "WFP; UNICEF"
        )

    def test_theme_splits(self):
        result = ScannerMappingMixin._split_if_multival(
            "theme", "Food Security; Nutrition; Climate"
        )
        assert result == ["Food Security", "Nutrition", "Climate"]

    def test_region_splits(self):
        result = ScannerMappingMixin._split_if_multival(
            "region", "East Africa; West Africa"
        )
        assert result == ["East Africa", "West Africa"]

    def test_language_splits(self):
        result = ScannerMappingMixin._split_if_multival("language", "English; French")
        assert result == ["English", "French"]

    def test_non_string_passthrough(self):
        assert ScannerMappingMixin._split_if_multival("country", 42) == 42
        assert ScannerMappingMixin._split_if_multival("country", ["a", "b"]) == [
            "a",
            "b",
        ]
        assert ScannerMappingMixin._split_if_multival("country", None) is None

    def test_no_semicolon_unchanged(self):
        assert (
            ScannerMappingMixin._split_if_multival("country", "Kenya, Rwanda")
            == "Kenya, Rwanda"
        )
