"""
Tests for visual content metadata (images and tables) in chunks.

Verifies that:
1. Images metadata is extracted and saved during parsing
2. Table metadata includes bbox and position_hint
3. Chunks contain images array for their page
4. Position hints are correctly calculated
"""

import json
from unittest.mock import Mock


class TestImageMetadataExtraction:
    """Test image metadata extraction in parser."""

    def test_save_images_metadata_creates_json(self, tmp_path):
        """Verify _save_images_metadata creates images_metadata.json."""
        from pipeline.processors.parsing.parser import ParseProcessor

        # Create mock document with PictureItems
        mock_document = Mock()

        # Create a mock PictureItem
        mock_picture = Mock()
        mock_picture.__class__.__name__ = "PictureItem"
        mock_picture.self_ref = "#/pictures/0"
        mock_prov = Mock()
        mock_prov.page_no = 1
        mock_prov.bbox = Mock()
        mock_prov.bbox.as_tuple.return_value = (100.0, 200.0, 300.0, 400.0)
        mock_picture.prov = [mock_prov]

        mock_document.iterate_items.return_value = [(mock_picture, 0)]

        # Create output folder with markdown file containing image reference
        output_folder = tmp_path / "parsed_doc"
        output_folder.mkdir()
        images_dir = output_folder / "images"
        images_dir.mkdir()

        md_file = output_folder / "test.md"
        md_file.write_text("# Test\n\n![Image](images/image_000.png)\n")

        # Test the method
        parser = ParseProcessor(output_dir=str(tmp_path))
        result = parser._save_images_metadata(mock_document, str(output_folder))

        # Verify result
        assert "0" in result
        assert result["0"]["page"] == 1
        assert result["0"]["bbox"] == [100.0, 200.0, 300.0, 400.0]
        assert "position_hint" in result["0"]

        # Verify JSON file was created
        meta_file = images_dir / "images_metadata.json"
        assert meta_file.exists()

        with open(meta_file) as f:
            saved_meta = json.load(f)
        assert "0" in saved_meta

    def test_position_hint_calculation(self, tmp_path):
        """Verify position_hint is calculated correctly (bbox.top / page_height)."""
        from pipeline.processors.parsing.parser import ParseProcessor

        mock_document = Mock()
        mock_picture = Mock()
        mock_picture.__class__.__name__ = "PictureItem"
        mock_picture.self_ref = "#/pictures/0"
        mock_prov = Mock()
        mock_prov.page_no = 1
        # bbox = (min_x, min_y, max_x, max_y) = (0, 421, 100, 500)
        # position_hint = (page_height - bbox[3]) / page_height = (842 - 500) / 842 = 0.406
        mock_prov.bbox = Mock()
        mock_prov.bbox.as_tuple.return_value = (0, 421.0, 100, 500)
        mock_picture.prov = [mock_prov]

        mock_document.iterate_items.return_value = [(mock_picture, 0)]

        output_folder = tmp_path / "parsed_doc"
        output_folder.mkdir()
        (output_folder / "images").mkdir()
        (output_folder / "test.md").write_text("![Image](images/img.png)")

        parser = ParseProcessor(output_dir=str(tmp_path))
        result = parser._save_images_metadata(mock_document, str(output_folder))

        # Position hint = (page_height - bbox_bottom) / page_height = (842 - 500) / 842 ≈ 0.406
        expected_hint = (842 - 500) / 842
        assert abs(result["0"]["position_hint"] - expected_hint) < 0.01


class TestChunkerTableMetadata:
    """Test table metadata extraction in Chunker."""

    def test_build_table_index_map_extracts_position_hint(self):
        """Verify _build_table_index_map extracts bbox and position_hint."""
        from unittest.mock import MagicMock

        from pipeline.processors.indexing.chunker import Chunker

        # Create mock tokenizer
        mock_tokenizer = MagicMock()
        mock_chunker = MagicMock()

        chunker = Chunker(tokenizer=mock_tokenizer, chunker=mock_chunker)

        # Create mock DoclingDocument with a TableItem
        mock_doc = MagicMock()
        mock_table = MagicMock()
        mock_table.__class__.__name__ = "TableItem"
        mock_table.self_ref = "#/tables/0"

        # Setup provenance with bbox
        mock_prov = MagicMock()
        mock_prov.page_no = 5
        mock_prov.bbox = MagicMock()
        mock_prov.bbox.as_tuple.return_value = (50.0, 100.0, 400.0, 600.0)
        mock_table.prov = [mock_prov]

        mock_doc.iterate_items.return_value = [(mock_table, 0)]

        # Call the real method
        result = chunker._build_table_index_map(mock_doc)

        # Verify the output structure
        assert "#/tables/0" in result
        table_info = result["#/tables/0"]
        assert table_info["idx"] == 0
        assert table_info["page"] == 5
        assert list(table_info["bbox"]) == [50.0, 100.0, 400.0, 600.0]
        assert "position_hint" in table_info
        # position_hint = (842 - 600) / 842 ≈ 0.287
        expected_hint = (842 - 600) / 842
        assert abs(table_info["position_hint"] - expected_hint) < 0.01


class TestChunkerImageExtraction:
    """Test image extraction for chunks."""

    def test_extract_chunk_images_returns_correct_structure(self):
        """Verify _extract_chunk_images returns images with required fields."""
        from unittest.mock import MagicMock

        from pipeline.processors.indexing.chunker import Chunker

        mock_tokenizer = MagicMock()
        mock_chunker = MagicMock()
        chunker = Chunker(tokenizer=mock_tokenizer, chunker=mock_chunker)

        # Setup mock elements (not images)
        elements = [{"element_type": "text", "text": "Some text"}]

        # Setup images_by_page with image on page 1
        images_by_page = {
            1: [
                {
                    "path": "images/image_000.png",
                    "bbox": [100.0, 200.0, 300.0, 400.0],
                    "position_hint": 0.525,
                    "page": 1,
                }
            ]
        }

        page_nums = {1}

        # Call the real method
        result = chunker._extract_chunk_images(elements, images_by_page, page_nums)

        # Verify structure
        assert len(result) == 1
        img = result[0]
        assert "path" in img
        assert "bbox" in img
        assert "position_hint" in img
        assert "page" in img
        assert img["path"] == "images/image_000.png"


class TestChunkerElementOrdering:
    """Test that chunk elements are sorted by position."""

    def test_build_chunk_elements_sorts_by_position(self):
        """Verify _build_chunk_elements sorts elements by page and position_hint."""
        from unittest.mock import MagicMock

        from pipeline.processors.indexing.chunker import Chunker

        mock_tokenizer = MagicMock()
        mock_chunker = MagicMock()
        chunker = Chunker(tokenizer=mock_tokenizer, chunker=mock_chunker)

        # Create tables with different positions
        tables = [
            {
                "num_rows": 3,
                "num_cols": 2,
                "rows": [],
                "page": 1,
                "position_hint": 0.8,  # Near bottom
            },
            {
                "num_rows": 5,
                "num_cols": 3,
                "rows": [],
                "page": 1,
                "position_hint": 0.2,  # Near top
            },
        ]

        # Text elements
        elements = [
            {
                "element_type": "text",
                "text": "Middle text",
                "page": 1,
                "position_hint": 0.5,
            }
        ]

        images_by_page = {}
        page_nums = {1}

        # Call the real method
        result = chunker._build_chunk_elements(
            tables, elements, images_by_page, page_nums
        )

        # Verify elements are sorted by position_hint
        position_hints = [elem.get("position_hint", 0) for elem in result]
        assert position_hints == sorted(
            position_hints
        ), "Elements should be sorted by position_hint"


class TestPositionHintCalculation:
    """Test position_hint calculation in real parser and chunker code."""

    def test_parser_calculates_position_hint_correctly(self, tmp_path):
        """Verify parser._save_images_metadata calculates position_hint using correct formula."""
        from unittest.mock import Mock

        from pipeline.processors.parsing.parser import ParseProcessor

        mock_document = Mock()
        mock_picture = Mock()
        mock_picture.__class__.__name__ = "PictureItem"
        mock_picture.self_ref = "#/pictures/0"
        mock_prov = Mock()
        mock_prov.page_no = 1
        # bbox with bottom at y=600 (out of 842 page height)
        mock_prov.bbox = Mock()
        mock_prov.bbox.as_tuple.return_value = (50.0, 100.0, 400.0, 600.0)
        mock_picture.prov = [mock_prov]

        mock_document.iterate_items.return_value = [(mock_picture, 0)]

        output_folder = tmp_path / "parsed_doc"
        output_folder.mkdir()
        (output_folder / "images").mkdir()
        (output_folder / "test.md").write_text("![Image](images/img.png)")

        parser = ParseProcessor(output_dir=str(tmp_path))
        result = parser._save_images_metadata(mock_document, str(output_folder))

        # Position hint = (842 - 600) / 842 ≈ 0.287
        expected_hint = (842 - 600) / 842
        assert abs(result["0"]["position_hint"] - expected_hint) < 0.01

    def test_chunker_calculates_position_hint_correctly(self):
        """Verify chunker._build_table_index_map calculates position_hint using correct formula."""
        from unittest.mock import MagicMock

        from pipeline.processors.indexing.chunker import Chunker

        mock_tokenizer = MagicMock()
        mock_chunker = MagicMock()
        chunker = Chunker(tokenizer=mock_tokenizer, chunker=mock_chunker)

        mock_doc = MagicMock()
        mock_table = MagicMock()
        mock_table.__class__.__name__ = "TableItem"
        mock_table.self_ref = "#/tables/0"

        mock_prov = MagicMock()
        mock_prov.page_no = 1
        # bbox with bottom at y=600 (same as parser test)
        mock_prov.bbox = MagicMock()
        mock_prov.bbox.as_tuple.return_value = (50.0, 100.0, 400.0, 600.0)
        mock_table.prov = [mock_prov]

        mock_doc.iterate_items.return_value = [(mock_table, 0)]

        result = chunker._build_table_index_map(mock_doc)

        # Position hint = (842 - 600) / 842 ≈ 0.287 (same formula as parser)
        expected_hint = (842 - 600) / 842
        assert abs(result["#/tables/0"]["position_hint"] - expected_hint) < 0.01


class TestImagesMetadataFileCreation:
    """Test the actual creation of images_metadata.json by the parser."""

    def test_images_metadata_written_with_all_fields(self, tmp_path):
        """Verify images_metadata.json contains all required fields when written by parser."""
        from pipeline.processors.parsing.parser import ParseProcessor

        mock_document = Mock()

        # Create multiple mock pictures
        mock_pictures = []
        for i in range(2):
            mock_picture = Mock()
            mock_picture.__class__.__name__ = "PictureItem"
            mock_picture.self_ref = f"#/pictures/{i}"
            mock_prov = Mock()
            mock_prov.page_no = i + 1
            mock_prov.bbox = Mock()
            mock_prov.bbox.as_tuple.return_value = (
                50.0 * i,
                100.0 * i,
                200.0 + 50 * i,
                300.0 + 100 * i,
            )
            mock_picture.prov = [mock_prov]
            mock_pictures.append((mock_picture, i))

        mock_document.iterate_items.return_value = mock_pictures

        output_folder = tmp_path / "parsed_doc"
        output_folder.mkdir()
        images_dir = output_folder / "images"
        images_dir.mkdir()
        (output_folder / "test.md").write_text(
            "![](images/image_000.png)\n![](images/image_001.png)"
        )

        parser = ParseProcessor(output_dir=str(tmp_path))
        result = parser._save_images_metadata(mock_document, str(output_folder))

        # Verify all required fields are present for each image
        required_fields = ["page", "bbox", "position_hint"]
        for idx in ["0", "1"]:
            assert idx in result, f"Missing image {idx}"
            for field in required_fields:
                assert field in result[idx], f"Image {idx} missing field: {field}"

            # Verify bbox is a list of 4 coordinates
            assert isinstance(result[idx]["bbox"], list)
            assert len(result[idx]["bbox"]) == 4

            # Verify position_hint is between 0 and 1
            assert 0 <= result[idx]["position_hint"] <= 1


class TestTableImagesMetadata:
    """Test table image metadata extraction."""

    def test_table_metadata_included_in_chunk(self):
        """Verify table metadata (bbox, position_hint) flows through to chunks."""
        from unittest.mock import MagicMock

        from pipeline.processors.indexing.chunker import Chunker

        mock_tokenizer = MagicMock()
        mock_chunker_instance = MagicMock()
        chunker = Chunker(tokenizer=mock_tokenizer, chunker=mock_chunker_instance)

        # Create mock DoclingDocument with a table
        mock_doc = MagicMock()
        mock_table = MagicMock()
        mock_table.__class__.__name__ = "TableItem"
        mock_table.self_ref = "#/tables/0"

        mock_prov = MagicMock()
        mock_prov.page_no = 2
        mock_prov.bbox = MagicMock()
        mock_prov.bbox.as_tuple.return_value = (50.0, 100.0, 400.0, 600.0)
        mock_table.prov = [mock_prov]

        mock_doc.iterate_items.return_value = [(mock_table, 0)]

        # Call real method to build table index
        table_index = chunker._build_table_index_map(mock_doc)

        # Verify table metadata structure that will flow to chunks
        assert "#/tables/0" in table_index
        table_meta = table_index["#/tables/0"]

        # These are the fields used by _process_single_chunk to enrich chunks
        assert "idx" in table_meta
        assert "page" in table_meta
        assert "bbox" in table_meta
        assert "position_hint" in table_meta

        # Verify values
        assert table_meta["page"] == 2
        assert len(list(table_meta["bbox"])) == 4
        assert 0 <= table_meta["position_hint"] <= 1
