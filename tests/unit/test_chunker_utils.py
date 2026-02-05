from pipeline.processors.indexing.chunker import Chunker


def test_is_reference_element_recognizes_footnotes():
    chunker = Chunker()

    assert chunker._is_reference_element("1 First footnote", "footnote") is True
    assert chunker._is_reference_element("^2 Second footnote", "endnote") is True
    assert chunker._is_reference_element("[3] Third footnote", "footnote") is True
    assert chunker._is_reference_element("<sup>4</sup> Fourth", "footnote") is True
    assert chunker._is_reference_element("Plain text", "text") is False


def test_clean_text_fixes_replacement_chars_and_spacing():
    chunker = Chunker()

    assert chunker._clean_text("D\ufffdmocra\ufffdque") == "Démocratique"
    assert chunker._clean_text("See ^12 text") == "See [^12] text"
    assert chunker._clean_text("D a t a   s o u r c e s") == "Data sources"


def test_should_include_image_with_tolerance():
    chunker = Chunker()
    text_range = {"min_y": 100, "max_y": 200}

    assert chunker._should_include_image([0, 150, 10, 160], text_range, False) is True
    assert chunker._should_include_image([0, 10, 10, 20], text_range, False) is False
    assert chunker._should_include_image([0, 10, 10, 20], text_range, True) is True


def test_filter_images_before_text_respects_captions():
    chunker = Chunker()
    elements = [
        {"element_type": "image", "id": "img-1"},
        {"element_type": "text", "label": "body", "text": "Content"},
        {"element_type": "image", "id": "img-2"},
    ]
    filtered = chunker._filter_images_before_text(elements)
    assert filtered[0]["element_type"] == "text"
    assert filtered[1]["id"] == "img-2"

    caption_first = [
        {"element_type": "image", "id": "img-1"},
        {"element_type": "text", "label": "caption", "text": "Figure 1"},
    ]
    filtered_caption = chunker._filter_images_before_text(caption_first)
    assert filtered_caption[0]["element_type"] == "image"


def test_filter_table_metadata_text_removes_sheet_markers():
    chunker = Chunker()
    elements = [
        {
            "element_type": "text",
            "text": "Best match (score 71): [Sheet: Unemployment]",
        },
        {"element_type": "text", "text": "Table shows results."},
    ]
    filtered = chunker._filter_table_metadata_text(elements)
    assert len(filtered) == 1
    assert filtered[0]["text"] == "Table shows results."
