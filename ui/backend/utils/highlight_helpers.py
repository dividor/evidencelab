import asyncio
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

import utils.llm_factory as llm_factory
from pipeline.utilities.text_cleaning import clean_text
from ui.backend.schemas import HighlightBox, HighlightMatch, UnifiedHighlightRequest

HIGHLIGHT_CACHE: Dict[Tuple[str, int], str] = {}


def build_clean_text_index_map(text: str) -> tuple[str, list[int]]:
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


def find_exact_phrase_matches(
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


def find_word_matches(
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


def dedupe_matches(matches: list[HighlightMatch]) -> list[HighlightMatch]:
    matches.sort(key=lambda m: m.start)
    unique_matches: list[HighlightMatch] = []
    seen_positions = set()
    for match in matches:
        if match.start not in seen_positions:
            unique_matches.append(match)
            seen_positions.add(match.start)
    return unique_matches


def merge_overlapping_matches(
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


def render_highlighted_text(text: str, matches: list[HighlightMatch]) -> str:
    highlighted_text = ""
    last_end = 0
    for match in matches:
        highlighted_text += text[last_end : match.start]
        highlighted_text += f"<em>{text[match.start:match.end]}</em>"
        last_end = match.end
    highlighted_text += text[last_end:]
    return highlighted_text


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


@traceable(name="SemanticHighlighting")
async def get_semantic_llm_output(
    query: str,
    clean_text: str,
    request: UnifiedHighlightRequest,
) -> str:
    prompts_dir = Path(__file__).resolve().parents[3] / "prompts"
    jinja_env = Environment(loader=FileSystemLoader(str(prompts_dir)), autoescape=True)
    system_template = jinja_env.get_template("semantic_highlight_system.j2")
    user_template = jinja_env.get_template("semantic_highlight_user.j2")
    system_prompt = system_template.render()
    user_prompt = user_template.render(query=query, text=clean_text)

    semantic_config = request.semantic_model_config
    model_key = semantic_config.model if semantic_config else None
    temperature = semantic_config.temperature if semantic_config else None
    max_tokens = semantic_config.max_tokens if semantic_config else None
    llm = llm_factory.get_llm(
        model=model_key, temperature=temperature, max_tokens=max_tokens
    )

    cache_key = (query, hash(clean_text))
    if cache_key in HIGHLIGHT_CACHE:
        return HIGHLIGHT_CACHE[cache_key]

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    llm_output = response.content.strip()
    if "```json" in llm_output:
        llm_output = llm_output.split("```json")[1].split("```")[0].strip()
    elif "```" in llm_output:
        llm_output = llm_output.split("```")[1].split("```")[0].strip()

    if len(HIGHLIGHT_CACHE) > 1000:
        HIGHLIGHT_CACHE.clear()
    HIGHLIGHT_CACHE[cache_key] = llm_output
    return llm_output


def parse_semantic_phrases(llm_output: str) -> list[str]:
    phrases = llm_output
    if isinstance(llm_output, str):
        phrases = json.loads(llm_output)
    if not isinstance(phrases, list):
        return []
    return phrases


async def find_semantic_matches(
    phrases: list[str],
    clean_text: str,
    text: str,
    index_map: list[int],
) -> list[HighlightMatch]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        find_semantic_matches_sync,
        phrases,
        clean_text,
        text,
        index_map,
    )


def bbox_from_payload(bbox_data: Any) -> Optional[Dict[str, Any]]:
    if isinstance(bbox_data, dict):
        return bbox_data
    if isinstance(bbox_data, (list, tuple)) and len(bbox_data) >= 4:
        return {
            "l": bbox_data[0],
            "b": bbox_data[1],
            "r": bbox_data[2],
            "t": bbox_data[3],
        }
    return None


def highlight_boxes_from_chunk(
    payload: Dict[str, Any],
    *,
    page: Optional[int],
    text_filter: Optional[str],
    truncate: int,
) -> List[HighlightBox]:
    chunk_text = clean_text(payload.get("sys_text", ""))
    chunk_page = payload.get("sys_page_num")
    chunk_bboxes = payload.get("sys_bbox", [])
    if page and chunk_page != page:
        return []
    if text_filter and text_filter.lower() not in chunk_text.lower():
        return []
    highlights = []
    for bbox_data in chunk_bboxes:
        if not bbox_data:
            continue
        bbox = bbox_from_payload(bbox_data)
        if not bbox:
            continue
        if all(k in bbox for k in ["l", "t", "r", "b"]):
            highlights.append(
                HighlightBox(
                    page=chunk_page,
                    bbox=bbox,
                    text=chunk_text[:truncate],
                )
            )
    return highlights
