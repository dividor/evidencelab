import asyncio
import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from qdrant_client.http import models as qmodels

from pipeline.utilities.text_cleaning import clean_text
from ui.backend.schemas import (
    HighlightBox,
    HighlightMatch,
    HighlightResponse,
    UnifiedHighlightRequest,
    UnifiedHighlightResponse,
)
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source, logger
from ui.backend.utils.highlight_helpers import (
    build_clean_text_index_map,
    dedupe_matches,
    find_exact_phrase_matches,
    find_semantic_matches,
    find_word_matches,
    get_semantic_llm_output,
    highlight_boxes_from_chunk,
    merge_overlapping_matches,
    parse_semantic_phrases,
    render_highlighted_text,
)

router = APIRouter()
_highlight_cache: Dict[Any, Any] = {}


def _bbox_gaps(bboxes: List[tuple]) -> List[float]:
    sorted_bboxes = sorted(bboxes, key=lambda b: b[1] if len(b) >= 2 else 0)
    gaps = []
    for i in range(len(sorted_bboxes) - 1):
        if len(sorted_bboxes[i]) >= 4 and len(sorted_bboxes[i + 1]) >= 2:
            curr_bottom = sorted_bboxes[i][3]
            next_top = sorted_bboxes[i + 1][1]
            gaps.append(abs(curr_bottom - next_top))
    return gaps


def _bbox_gap_threshold(gaps: List[float]) -> tuple[float, List[float]]:
    sorted_gaps = sorted(gaps)
    baseline_idx = int(len(sorted_gaps) * 0.75)
    baseline_gap = sorted_gaps[baseline_idx]
    threshold = baseline_gap * 2.5
    large_gaps = [g for g in gaps if g > threshold]
    return threshold, large_gaps


def _apply_paragraph_breaks(text: str, large_gaps: List[float]) -> str:
    if not large_gaps:
        return text
    sentences = re.split(r"(\.\s+(?=[A-ZÁÉÍÓÚÑ]))", text)
    if len(sentences) <= 2:
        return text
    break_frequency = max(2, len(sentences) // (len(large_gaps) + 1))
    result_parts = []
    for i, part in enumerate(sentences):
        result_parts.append(part)
        if i > 0 and i % (break_frequency * 2) == 0 and ". " in part:
            result_parts.append("\n\n")
    return "".join(result_parts)


def infer_paragraphs_from_bboxes(text: str, bboxes: List[tuple]) -> str:
    """
    Infer paragraph breaks in text based on vertical gaps in bounding boxes.
    """
    if not bboxes or len(bboxes) < 3:
        return text

    try:
        gaps = _bbox_gaps(bboxes)
        if not gaps or len(gaps) < 2:
            return text
        threshold, large_gaps = _bbox_gap_threshold(gaps)
        logger.info(
            "Bbox analysis: %s boxes, %s large gaps (threshold: %.2f)",
            len(bboxes),
            len(large_gaps),
            threshold,
        )
        return _apply_paragraph_breaks(text, large_gaps)
    except Exception as e:
        logger.warning(f"Error inferring paragraphs from bboxes: {e}")
        return text


def _normalize_bbox_entry(
    bbox_data: Any, chunk_payload: Dict[str, Any]
) -> Optional[tuple[int, Dict[str, float]]]:
    if not bbox_data:
        return None
    if isinstance(bbox_data, (list, tuple)) and len(bbox_data) == 2:
        page_num, bbox_tuple = bbox_data
        if isinstance(bbox_tuple, (list, tuple)) and len(bbox_tuple) >= 4:
            bbox = {
                "l": bbox_tuple[0],
                "b": bbox_tuple[1],
                "r": bbox_tuple[2],
                "t": bbox_tuple[3],
            }
            return page_num, bbox
        return None
    if isinstance(bbox_data, (list, tuple)) and len(bbox_data) >= 4:
        page_num = chunk_payload.get("sys_page_num")
        bbox = {
            "l": bbox_data[0],
            "b": bbox_data[1],
            "r": bbox_data[2],
            "t": bbox_data[3],
        }
        return page_num, bbox
    if isinstance(bbox_data, dict):
        page_num = chunk_payload.get("sys_page_num")
        return page_num, bbox_data
    return None


@router.get("/highlight/chunk/{chunk_id}", response_model=HighlightResponse)
async def get_chunk_highlights(
    chunk_id: str,
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Get bounding boxes for a specific chunk.
    Returns all bboxes for the chunk, with their correct page numbers.
    Chunks can span multiple pages.
    """
    try:
        chunk_payload = None
        try:
            pg = get_pg_for_source(data_source)
            chunk_payload = pg.fetch_chunks([chunk_id]).get(str(chunk_id))
        except Exception:
            chunk_payload = None
        if not chunk_payload:
            db = get_db_for_source(data_source)
            if db and getattr(db, "client", None):
                results = db.client.retrieve(
                    collection_name=db.chunks_collection, ids=[chunk_id]
                )
                if results:
                    chunk_payload = results[0].payload
        if not chunk_payload:
            return HighlightResponse(highlights=[], total=0)
        chunk_bboxes = chunk_payload.get("sys_bbox", [])
        chunk_text = clean_text(chunk_payload.get("sys_text", ""))

        highlights = []

        # Convert bboxes to highlight format
        # Bboxes are now stored as (page, bbox_tuple) pairs
        for bbox_data in chunk_bboxes:
            normalized = _normalize_bbox_entry(bbox_data, chunk_payload)
            if not normalized:
                continue
            page_num, bbox = normalized
            if all(k in bbox for k in ["l", "t", "r", "b"]):
                highlights.append(
                    HighlightBox(
                        page=page_num,
                        bbox=bbox,
                        text=chunk_text[:2000],
                    )
                )

        return HighlightResponse(highlights=highlights, total=len(highlights))

    except Exception as e:
        logger.error(f"Chunk highlight error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/highlight/{doc_id}", response_model=HighlightResponse)
async def get_highlights(
    doc_id: str,
    page: Optional[int] = Query(None, description="Filter by page number"),
    text: Optional[str] = Query(
        None,
        description="Filter by text content (not recommended - use page filter instead)",
    ),
    data_source: Optional[str] = Query(
        None, description="Data source (e.g., 'uneg', 'gcf')"
    ),
):
    """
    Get bounding box data for highlighting chunks on pages.

    Note: Text filtering may miss results due to semantic vs literal matching.
    For best results, filter by page only and let all chunks on that page be highlighted.
    """
    try:
        results = []
        try:
            pg = get_pg_for_source(data_source)
            results = pg.fetch_chunks_for_doc(doc_id)
        except Exception:
            results = []

        if not results:
            db = get_db_for_source(data_source)
            if db and getattr(db, "client", None):
                q_results, _ = db.client.scroll(
                    collection_name=db.chunks_collection,
                    scroll_filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="doc_id", match=qmodels.MatchValue(value=doc_id)
                            )
                        ]
                    ),
                    limit=10000,
                    with_payload=True,
                )
                results = [result.payload for result in q_results if result.payload]

        highlights = []
        for chunk_payload in results:
            highlights.extend(
                highlight_boxes_from_chunk(
                    chunk_payload, page=page, text_filter=text, truncate=100
                )
            )

        return HighlightResponse(highlights=highlights, total=len(highlights))

    except Exception as e:
        logger.error(f"Highlight error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _best_phrase_match(
    clean_lower: str, phrase_clean: str
) -> tuple[Optional[tuple[int, int]], float]:
    best_match = None
    best_ratio = 0.0
    phrase_len = len(phrase_clean)
    if phrase_len > len(clean_lower):
        return None, 0.0
    for i in range(len(clean_lower) - phrase_len + 1):
        window = clean_lower[i : i + phrase_len]
        if window[0] != phrase_clean[0]:
            continue
        ratio = SequenceMatcher(None, phrase_clean, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = (i, i + phrase_len)
        if i + phrase_len + 20 <= len(clean_lower):
            window_expanded = clean_lower[i : i + phrase_len + 20]
            ratio_exp = SequenceMatcher(None, phrase_clean, window_expanded).ratio()
            if ratio_exp > best_ratio:
                best_ratio = ratio_exp
                best_match = (i, i + phrase_len + 20)
    return best_match, best_ratio


def _map_match_indices(
    index_map: List[int], best_match: tuple[int, int]
) -> tuple[int, int]:
    start, end = best_match
    orig_start = index_map[start]
    if end - 1 < len(index_map):
        orig_end = index_map[end - 1] + 1
    else:
        orig_end = index_map[-1]
    return orig_start, orig_end


def find_semantic_matches_sync(
    phrases: List[str], clean_text: str, original_text: str, index_map: List[int]
) -> List[HighlightMatch]:
    """
    CPU-bound matching logic run in threadpool.
    Uses original fuzzy matching (SequenceMatcher) to ensure robust detection of LLM phrases.
    """
    # We need a logger here since it's running in a thread
    semantic_matches: List[HighlightMatch] = []
    clean_lower = clean_text.lower()

    for phrase in phrases:
        if not isinstance(phrase, str) or len(phrase.strip()) < 3:
            continue
        phrase_clean = phrase.strip().lower()
        best_match, best_ratio = _best_phrase_match(clean_lower, phrase_clean)
        if not best_match or best_ratio <= 0.75:
            continue
        orig_start, orig_end = _map_match_indices(index_map, best_match)
        matched_text = original_text[orig_start:orig_end]
        semantic_matches.append(
            HighlightMatch(
                start=orig_start,
                end=orig_end,
                text=matched_text,
                match_type="semantic",
                similarity=float(best_ratio),
            )
        )

    return semantic_matches


def _build_clean_text_index_map(text: str) -> tuple[str, list[int]]:
    clean_chars: List[str] = []
    index_map: List[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "<":
            j = text.find(">", i)
            if j != -1:
                i = j + 1
                continue
        clean_chars.append(text[i])
        index_map.append(i)
        i += 1
    index_map.append(n)
    return "".join(clean_chars), index_map


def _find_exact_phrase_matches(
    clean_text: str, index_map: list[int], text: str, query: str
) -> list[HighlightMatch]:
    lower_clean = clean_text.lower()
    lower_query = query.lower()
    matches: list[HighlightMatch] = []
    start_index = 0
    while start_index < len(lower_clean):
        index = lower_clean.find(lower_query, start_index)
        if index == -1:
            break
        orig_start = index_map[index]
        orig_end = index_map[index + len(lower_query) - 1] + 1
        matches.append(
            HighlightMatch(
                start=orig_start,
                end=orig_end,
                text=text[orig_start:orig_end],
                match_type="exact_phrase",
            )
        )
        start_index = index + 1
    return matches


def _find_word_matches(
    clean_text: str, index_map: list[int], text: str, query: str
) -> list[HighlightMatch]:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "will",
        "with",
        "me",
        "about",
        "tell",
    }
    lower_clean = clean_text.lower()
    lower_query = query.lower()
    query_words = [
        word
        for word in lower_query.split()
        if word and word not in stop_words and len(word) > 2
    ]
    if not query_words:
        return []

    keyword_matches: list[HighlightMatch] = []
    for word in query_words:
        start_index = 0
        while start_index < len(lower_clean):
            index = lower_clean.find(word, start_index)
            if index == -1:
                break
            before_char = lower_clean[index - 1] if index > 0 else " "
            after_char = (
                lower_clean[index + len(word)]
                if index + len(word) < len(lower_clean)
                else " "
            )
            is_word_boundary = re.match(r"\W", before_char) and re.match(
                r"\W", after_char
            )
            if is_word_boundary:
                orig_start = index_map[index]
                orig_end = index_map[index + len(word) - 1] + 1
                keyword_matches.append(
                    HighlightMatch(
                        start=orig_start,
                        end=orig_end,
                        text=text[orig_start:orig_end],
                        match_type="word",
                        word=word,
                    )
                )
            start_index = index + 1
    return keyword_matches


def _dedupe_matches(matches: list[HighlightMatch]) -> list[HighlightMatch]:
    matches.sort(key=lambda m: m.start)
    unique_matches: list[HighlightMatch] = []
    seen_positions = set()
    for match in matches:
        if match.start not in seen_positions:
            unique_matches.append(match)
            seen_positions.add(match.start)
    return unique_matches


def _merge_overlapping_matches(
    matches: list[HighlightMatch], text: str
) -> list[HighlightMatch]:
    sorted_matches = sorted(matches, key=lambda m: m.start)
    merged_matches: list[HighlightMatch] = []
    for match in sorted_matches:
        if not merged_matches:
            merged_matches.append(match)
            continue
        last = merged_matches[-1]
        if match.start <= last.end:
            merged_matches[-1] = HighlightMatch(
                start=last.start,
                end=max(last.end, match.end),
                text=text[last.start : max(last.end, match.end)],
                match_type=last.match_type,
                word=last.word,
                similarity=last.similarity,
            )
        else:
            merged_matches.append(match)
    return merged_matches


def _render_highlighted_text(text: str, matches: list[HighlightMatch]) -> str:
    highlighted_text = ""
    last_end = 0
    for match in matches:
        highlighted_text += text[last_end : match.start]
        highlighted_text += f"<em>{text[match.start:match.end]}</em>"
        last_end = match.end
    highlighted_text += text[last_end:]
    return highlighted_text


def _get_highlight_cache() -> Dict[Any, Any]:
    return _highlight_cache


async def _get_semantic_llm_output(
    query: str, clean_text: str, request: UnifiedHighlightRequest
) -> str:
    cache = _get_highlight_cache()
    cache_key = (query, clean_text)
    if cache_key in cache:
        logger.info("Using cached LLM output for semantic highlighting")
        return cache[cache_key]

    llm_output = await get_semantic_llm_output(query, clean_text, request)
    cache[cache_key] = llm_output
    return llm_output


def _parse_semantic_phrases(llm_output: str) -> list[str]:
    try:
        parsed = json.loads(llm_output)
        if isinstance(parsed, dict) and "phrases" in parsed:
            phrases = parsed["phrases"]
            if isinstance(phrases, list):
                return [p for p in phrases if isinstance(p, str)]
    except json.JSONDecodeError:
        return []
    return []


async def _find_semantic_matches(
    phrases: List[str], clean_text: str, text: str, index_map: List[int]
) -> List[HighlightMatch]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        find_semantic_matches_sync,
        phrases,
        clean_text,
        text,
        index_map,
    )


@router.post("/highlight", response_model=UnifiedHighlightResponse)
async def highlight_text(request: UnifiedHighlightRequest):
    """
    Unified highlighting endpoint that supports keyword and/or semantic highlighting.

    Args:
        query: Search query
        text: Text to highlight within
        highlight_type: "keyword", "semantic", or "both" (default)
        semantic_threshold: Minimum similarity for semantic matches (default 0.4)
        min_sentence_length_ratio: Unused (kept for compatibility)

    Returns:
        Unified response with all requested highlight types
    """
    try:
        query = request.query.strip()
        text = request.text
        highlight_type = request.highlight_type.lower()

        if not query or not text:
            return UnifiedHighlightResponse(
                highlighted_text=text, matches=[], total=0, types_returned=[]
            )

        if highlight_type not in ["keyword", "semantic", "both"]:
            raise HTTPException(
                status_code=400,
                detail="highlight_type must be 'keyword', 'semantic', or 'both'",
            )

        # HTML-aware processing: build clean text and index map for highlighting.
        clean_text, index_map = build_clean_text_index_map(text)

        all_matches = []
        types_returned = []

        # KEYWORD HIGHLIGHTING
        if highlight_type in ["keyword", "both"]:
            keyword_matches = find_exact_phrase_matches(
                clean_text, index_map, text, query
            )
            if not keyword_matches:
                keyword_matches = find_word_matches(clean_text, index_map, text, query)
                keyword_matches = dedupe_matches(keyword_matches)

            if keyword_matches:
                all_matches.extend(keyword_matches)
                types_returned.append("keyword")
                logger.info(
                    "Found %s keyword matches for '%s'", len(keyword_matches), query
                )

        # SEMANTIC HIGHLIGHTING (LLM-based)
        if highlight_type in ["semantic", "both"]:
            try:
                llm_output = await get_semantic_llm_output(query, clean_text, request)
                try:
                    phrases = parse_semantic_phrases(llm_output)
                    semantic_matches = await find_semantic_matches(
                        phrases, clean_text, text, index_map
                    )
                    if semantic_matches:
                        all_matches.extend(semantic_matches)
                        types_returned.append("semantic")
                        logger.info(
                            "Found %s LLM semantic matches for '%s'",
                            len(semantic_matches),
                            query,
                        )
                except json.JSONDecodeError as e:
                    logger.error(
                        "Failed to parse LLM JSON: %s | Output: %s", e, llm_output
                    )
                except Exception as e:
                    logger.error("Error in semantic processing: %s", e)
                    logger.error("Failed to parse LLM JSON response: %s", e)
                    logger.error("LLM output: %s", llm_output)
            except Exception as e:
                logger.error("Semantic highlighting LLM error: %s", e, exc_info=True)

        logger.info(
            "Highlighting complete: %s total matches, types: %s",
            len(all_matches),
            types_returned,
        )

        # Generate highlighted HTML text with <em> tags
        merged_matches = merge_overlapping_matches(all_matches, text)
        highlighted_text = render_highlighted_text(text, merged_matches)

        return UnifiedHighlightResponse(
            highlighted_text=highlighted_text,
            matches=all_matches,
            total=len(all_matches),
            types_returned=types_returned,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Highlight error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
