#!/usr/bin/env python3
"""
Evaluate TOC category labels stored in the DB using an LLM judge.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from pipeline.db import Database, load_datasources_config  # noqa: E402
from pipeline.processors.tagging.tagger import SectionTypeTagger  # noqa: E402
from pipeline.processors.tagging.tagger_rules import (  # noqa: E402
    apply_keyword_locking,
    apply_sequence_rules,
    compile_keyword_rules,
    propagate_hierarchy,
)
from pipeline.processors.tagging.tagger_toc import parse_toc  # noqa: E402
from utils.llm_factory import get_llm  # noqa: E402

PROMPTS_DIR = PROJECT_ROOT / "prompts"
jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

JUDGE_LLM = "Qwen/Qwen2.5-72B-Instruct"
MAX_PROMPT_CHARS = 28000
DEFAULT_OUTPUT = PROJECT_ROOT / "logs" / "toc_category_eval.jsonl"
DEFAULT_LOG = PROJECT_ROOT / "logs" / "toc_category_eval.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge TOC category labels from DB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--records", type=int, help="Number of records to process")
    group.add_argument("--file-id", type=str, help="Process a single document by ID")
    parser.add_argument(
        "--data-source",
        type=str,
        default="uneg",
        help="Data source/collection suffix (default: uneg)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--overwrite-output",
        action="store_true",
        help="Overwrite output file instead of appending.",
    )
    parser.add_argument(
        "--append-output",
        action="store_true",
        help="Append to output/log files instead of overwriting.",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-run tagger on sys_toc before judging (no DB save).",
    )
    parser.add_argument(
        "--reclassify-no-llm",
        action="store_true",
        help="Reclassify using deterministic rules only (skip LLM).",
    )
    parser.add_argument(
        "--doc-ids-path",
        type=str,
        help="Path to JSON file storing fixed doc ids for repeatable runs.",
    )
    return parser.parse_args()


def resolve_llm_config(model_hint: str) -> Tuple[Dict[str, Any], str]:
    config = load_datasources_config()
    supported_llms = config.get("supported_llms", {})
    if model_hint in supported_llms:
        return supported_llms[model_hint], model_hint
    for key, cfg in supported_llms.items():
        if cfg.get("model") == model_hint:
            return cfg, key
    raise ValueError(f"{model_hint} not found in supported_llms config")


def build_llm():
    llm_config, model_key = resolve_llm_config(JUDGE_LLM)
    llm_model = llm_config.get("model")
    if not llm_model:
        raise ValueError(f"Model not specified for {model_key} in config")
    return get_llm(
        provider=llm_config.get("provider", "huggingface"),
        model=llm_model,
        temperature=0.0,
        max_tokens=512,
        inference_provider=llm_config.get("inference_provider"),
    )


def get_documents(limit: int, data_source: str) -> List[Any]:
    db = Database(data_source=data_source)
    collection_name = db.documents_collection
    results = []
    next_offset = None
    while len(results) < limit:
        points, next_offset = db.client.scroll(
            collection_name=collection_name,
            limit=max(limit - len(results), 50),
            with_payload=True,
            offset=next_offset,
        )
        if not points:
            break
        for point in points:
            if _payload_has_classified_toc(point.payload):
                results.append(point)
                if len(results) >= limit:
                    break
        if next_offset is None:
            break
    return results


def load_or_select_doc_ids(
    limit: int, data_source: str, doc_ids_path: Optional[str]
) -> List[Any]:
    if not doc_ids_path:
        return get_documents(limit, data_source)
    path = Path(doc_ids_path)
    if path.exists():
        doc_ids = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc_ids, list):
            raise ValueError("doc-ids-path must contain a JSON array of ids")
        db = Database(data_source=data_source)
        points = []
        for doc_id in doc_ids:
            retrieved = db.client.retrieve(
                collection_name=db.documents_collection,
                ids=[doc_id],
                with_payload=True,
            )
            if retrieved:
                points.append(retrieved[0])
        return points

    points = get_documents(limit, data_source)
    doc_ids = [point.id for point in points]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc_ids, ensure_ascii=False), encoding="utf-8")
    return points


def get_document_by_id(file_id: str, data_source: str) -> Any:
    db = Database(data_source=data_source)
    ids_to_try: list[str | int] = [file_id]
    if file_id.isdigit():
        ids_to_try.append(int(file_id))
    for id_val in ids_to_try:
        points = db.client.retrieve(
            collection_name=db.documents_collection,
            ids=[id_val],
            with_payload=True,
        )
        if points:
            return points[0]
    raise ValueError(
        f"Document {file_id} not found in collection {db.documents_collection}"
    )


def _payload_has_classified_toc(payload: dict) -> bool:
    toc = payload.get("toc_classified") or payload.get("sys_toc_classified")
    if isinstance(toc, str) and toc.strip():
        return True
    return False


def parse_classified_toc(toc_text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"^\s*\[H(?P<level>\d+)\]\s*(?P<title>.*?)\s*\|\s*(?P<label>[a-z_]+)"
        r"\s*(?:\|\s*page\s*(?P<page>\d+)\s*(?:\((?P<roman>[^)]*)\))?\s*(?:\[Front\])?)?\s*$"
    )
    for idx, line in enumerate(toc_text.splitlines()):
        match = pattern.match(line.strip())
        if not match:
            continue
        page = match.group("page")
        entries.append(
            {
                "idx": idx,
                "title": match.group("title").strip(),
                "label": match.group("label").strip(),
                "level": int(match.group("level")),
                "page": int(page) if page and page.isdigit() else None,
                "roman": match.group("roman").strip() if match.group("roman") else None,
            }
        )
    return entries


def _format_toc_list(toc_data: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for entry in toc_data:
        title = entry.get("label") or entry.get("title") or entry.get("text") or ""
        level = entry.get("level", 1)
        page = entry.get("page")
        if page is None:
            lines.append(f"[H{level}] {title}")
        else:
            lines.append(f"[H{level}] {title} | page {page}")
    return "\n".join(lines)


def _get_raw_toc_from_payload(payload: Dict[str, Any]) -> str:
    toc_data = payload.get("toc") or payload.get("sys_toc")
    if isinstance(toc_data, str):
        return toc_data
    if isinstance(toc_data, list):
        return _format_toc_list(toc_data)
    return ""


def _indent_toc_lines(toc_text: str) -> str:
    if not toc_text:
        return ""
    lines: List[str] = []
    pattern = re.compile(r"^\s*\[H(?P<level>\d+)\]\s*(?P<rest>.*)$")
    for raw_line in toc_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = pattern.match(line)
        if not match:
            lines.append(line)
            continue
        level = int(match.group("level"))
        indent = "  " * max(level - 1, 0)
        lines.append(f"{indent}[H{level}] {match.group('rest')}")
    return "\n".join(lines)


def _format_classified_toc(entries: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for entry in entries:
        level = entry.get("level", 1)
        title = entry.get("title", "")
        label = entry.get("label", "")
        page = entry.get("page")
        roman = entry.get("roman")
        fm_marker = entry.get("fm")
        indent = "  " * max(level - 1, 0)
        if page is None:
            line = f"{indent}[H{level}] {title} | {label}"
        else:
            roman_suffix = f" ({roman})" if roman else ""
            fm_suffix = " [Front]" if fm_marker else ""
            line = (
                f"{indent}[H{level}] {title} | {label} | page {page}"
                f"{roman_suffix}{fm_suffix}"
            )
        lines.append(line)
    return "\n".join(lines)


def _normalize_heading(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _match_rule_label(title: str) -> Optional[str]:
    if not title:
        return None
    normalized = title.strip().lower()
    for label, patterns in compile_keyword_rules():
        if any(pattern.search(normalized) for pattern in patterns):
            return label
    return None


def _rule_based_issues(
    entries: List[Dict[str, Any]],
    total_pages: Optional[int],
    roman_boundary_page: Optional[int],
    annex_start_idx: Optional[int],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    first_third_page = total_pages / 3 if total_pages and total_pages > 0 else None
    for entry in entries:
        title = entry.get("title") or ""
        expected_label = _match_rule_label(title)
        actual_label = entry.get("label")
        entry_page = entry.get("page")
        idx = entry.get("idx")
        if expected_label and actual_label != expected_label:
            issues.append(
                {
                    "type": "keyword_mismatch",
                    "idx": idx,
                    "title": title,
                    "page": entry_page,
                    "expected_label": expected_label,
                    "actual_label": actual_label,
                }
            )
        if actual_label == "front_matter":
            if first_third_page is not None and entry_page is not None:
                if entry_page > first_third_page:
                    issues.append(
                        {
                            "type": "front_matter_after_boundary",
                            "idx": idx,
                            "title": title,
                            "page": entry_page,
                        }
                    )
            if (
                roman_boundary_page is not None
                and entry_page is not None
                and entry_page > roman_boundary_page
            ):
                issues.append(
                    {
                        "type": "front_matter_after_roman_boundary",
                        "idx": idx,
                        "title": title,
                        "page": entry_page,
                    }
                )
        if (
            annex_start_idx is not None
            and actual_label == "annexes"
            and idx is not None
        ):
            if idx < annex_start_idx:
                issues.append(
                    {
                        "type": "annex_before_annex_start",
                        "idx": idx,
                        "title": title,
                        "page": entry_page,
                    }
                )
    return issues


def _compare_rule_based_to_db(
    db_entries: List[Dict[str, Any]], rule_entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    db_lookup: Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, Any]] = {}
    for entry in db_entries:
        key = (
            _normalize_heading(entry.get("title", "")),
            entry.get("page"),
            entry.get("level"),
        )
        db_lookup[key] = entry

    issues: List[Dict[str, Any]] = []
    seen_db_keys: set[Tuple[str, Optional[int], Optional[int]]] = set()
    for entry in rule_entries:
        key = (
            _normalize_heading(entry.get("title", "")),
            entry.get("page"),
            entry.get("level"),
        )
        db_entry = db_lookup.get(key)
        if not db_entry:
            issues.append(
                {
                    "type": "missing_db_entry",
                    "title": entry.get("title"),
                    "page": entry.get("page"),
                    "level": entry.get("level"),
                    "rule_label": entry.get("label"),
                }
            )
            continue
        seen_db_keys.add(key)
        db_label = db_entry.get("label")
        rule_label = entry.get("label")
        if db_label != rule_label:
            issues.append(
                {
                    "type": "label_mismatch",
                    "title": entry.get("title"),
                    "page": entry.get("page"),
                    "level": entry.get("level"),
                    "db_label": db_label,
                    "rule_label": rule_label,
                }
            )

    for key, entry in db_lookup.items():
        if key in seen_db_keys:
            continue
        issues.append(
            {
                "type": "missing_rule_entry",
                "title": entry.get("title"),
                "page": entry.get("page"),
                "level": entry.get("level"),
                "db_label": entry.get("label"),
            }
        )

    return issues


def _resolve_datasource_tag_config(data_source: str) -> Dict[str, Any]:
    config = load_datasources_config()
    datasources = config.get("datasources", {})
    for _, ds_config in datasources.items():
        if not isinstance(ds_config, dict):
            continue
        if ds_config.get("data_subdir") == data_source:
            return ds_config.get("pipeline", {}).get("tag", {})
    raise ValueError(f"Data source '{data_source}' not found in config.json")


def _build_tagger(data_source: str) -> SectionTypeTagger:
    tag_config = _resolve_datasource_tag_config(data_source)
    tagger = SectionTypeTagger(llm_config=tag_config)
    tagger.setup()
    tagger._database = None
    return tagger


def _reclassify_entries(
    tagger: SectionTypeTagger, payload: Dict[str, Any]
) -> List[Dict[str, Any]]:
    raw_toc = _get_raw_toc_from_payload(payload)
    if not raw_toc:
        return []
    document = {
        "id": payload.get("id") or payload.get("doc_id") or payload.get("file_id"),
        "sys_toc": raw_toc,
        "sys_page_count": payload.get("page_count") or payload.get("sys_page_count"),
    }
    toc_entries, labels_by_index = tagger._compute_document_toc_labels(document)
    if not toc_entries:
        return []
    entries: List[Dict[str, Any]] = []
    for entry in toc_entries:
        entries.append(
            {
                "idx": entry.get("index"),
                "title": entry.get("title"),
                "label": labels_by_index.get(entry.get("index"), "other"),
                "level": entry.get("level"),
                "page": entry.get("page"),
                "roman": entry.get("roman"),
            }
        )
    return entries


def _reclassify_entries_no_llm(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_toc = _get_raw_toc_from_payload(payload)
    if not raw_toc:
        return []
    toc_entries = parse_toc(raw_toc)
    if not toc_entries:
        return []
    locked_labels = apply_keyword_locking(toc_entries)
    final_labels = propagate_hierarchy(entries=toc_entries, labels=locked_labels)
    final_labels = apply_sequence_rules(
        entries=toc_entries,
        labels=final_labels,
        document={
            "page_count": payload.get("page_count"),
            "sys_page_count": payload.get("sys_page_count"),
        },
    )
    entries: List[Dict[str, Any]] = []
    for entry in toc_entries:
        entries.append(
            {
                "idx": entry.get("index"),
                "title": entry.get("title"),
                "label": final_labels.get(entry.get("index"), "other"),
                "level": entry.get("level"),
                "page": entry.get("page"),
                "roman": entry.get("roman"),
            }
        )
    return entries


def roman_to_int(token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    normalized = token.strip().upper()
    if not normalized:
        return None
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for char in reversed(normalized):
        value = roman_map.get(char)
        if value is None:
            return None
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def compute_roman_boundary(
    entries: List[Dict[str, Any]], total_pages: Optional[int]
) -> Optional[int]:
    roman_entries: List[Tuple[int, int]] = []
    for entry in entries:
        page = entry.get("page")
        roman_value = roman_to_int(entry.get("roman"))
        if page is None or roman_value is None:
            continue
        roman_entries.append((page, roman_value))
    if total_pages and total_pages > 0:
        first_third = total_pages / 3
        roman_entries = [
            (page, value) for page, value in roman_entries if page <= first_third
        ]
    if not roman_entries:
        return None
    roman_entries = sorted(set(roman_entries))
    runs: List[Tuple[int, int, int]] = []
    run_start = roman_entries[0][0]
    run_end = roman_entries[0][0]
    run_len = 1
    prev_value = roman_entries[0][1]
    for page, value in roman_entries[1:]:
        if value < prev_value:
            runs.append((run_len, run_start, run_end))
            run_start = page
            run_end = page
            run_len = 1
            prev_value = value
            continue
        run_end = page
        run_len += 1
        prev_value = value
    runs.append((run_len, run_start, run_end))
    long_runs = [run for run in runs if run[0] >= 2]
    selected = long_runs[-1] if long_runs else runs[-1]
    return selected[2]


def compute_annex_start_index(entries: List[Dict[str, Any]]) -> Optional[int]:
    patterns = [
        r"\bannex(es)?\b",
        r"\bannexe(s)?\b",
        r"\banexo(s)?\b",
        r"\bappendix\b",
        r"\bappendices\b",
        r"\battachment(s)?\b",
    ]
    annex_regex = re.compile("|".join(patterns), re.IGNORECASE)
    for entry in entries:
        title = entry.get("title") or ""
        label = entry.get("label")
        if label == "annexes" or annex_regex.search(title):
            return entry.get("idx")
    return None


def render_prompt(input_payload: Dict[str, Any]) -> str:
    tmpl = jinja_env.get_template("toc_category_judge.j2")
    prompt = tmpl.render(input_json=json.dumps(input_payload, ensure_ascii=False))
    return prompt[:MAX_PROMPT_CHARS]


def _extract_json_blob(text: str) -> Optional[str]:
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return None


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _fallback_parse(text: str) -> Optional[Dict[str, Any]]:
    verdict_match = re.search(r'"verdict"\s*:\s*"?([a-zA-Z]+)"?', text)
    score_match = re.search(r'"score"\s*:\s*([0-9]+)', text)
    if not verdict_match or not score_match:
        return None
    verdict = verdict_match.group(1).lower()
    if verdict not in {"pass", "fail"}:
        return None
    score = int(score_match.group(1))
    issues = []
    for issue_match in re.finditer(
        r'"idx"\s*:\s*(-?\d+)\s*,\s*"issue"\s*:\s*"([^"]+)"',
        text,
        re.DOTALL,
    ):
        issues.append({"idx": int(issue_match.group(1)), "issue": issue_match.group(2)})
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*)"', text)
    summary = summary_match.group(1) if summary_match else ""
    return {"verdict": verdict, "score": score, "issues": issues, "summary": summary}


def parse_llm_response(raw_text: str, prompt: str) -> Dict[str, Any]:
    text = raw_text.strip()
    json_blob = _extract_json_blob(text) or text
    try:
        parsed = json.loads(json_blob)
    except json.JSONDecodeError:
        parsed = _extract_first_json_object(json_blob)

    if isinstance(parsed, dict):
        verdict = parsed.get("verdict")
        score = parsed.get("score")
        issues = parsed.get("issues")
        if (
            verdict in {"pass", "fail"}
            and isinstance(score, int)
            and isinstance(issues, list)
        ):
            parsed["rendered_prompt"] = prompt
            return parsed

    fallback = _fallback_parse(json_blob)
    if fallback:
        fallback["rendered_prompt"] = prompt
        fallback["raw_response"] = raw_text[:2000]
        return fallback

    return {
        "verdict": "fail",
        "score": 0,
        "issues": [{"idx": -1, "issue": "Parse error: invalid JSON"}],
        "summary": "Invalid LLM response",
        "rendered_prompt": prompt,
        "raw_response": raw_text[:2000],
    }


def _filter_issues(
    issues: List[Dict[str, Any]],
    entries: List[Dict[str, Any]],
    roman_boundary_page: Optional[int],
    annex_start_idx: Optional[int],
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    roman_allowed = {"front_matter", "executive_summary", "acronyms"}
    annex_allowed = {"annexes", "appendix", "bibliography", "other"}

    for issue in issues:
        issue_text = issue.get("issue") if isinstance(issue, dict) else None
        if not issue_text:
            continue
        idx = issue.get("idx")
        if idx is None or idx < 0 or idx >= len(entries):
            filtered.append(issue)
            continue
        entry = entries[idx]
        entry_page = entry.get("page")
        entry_label = entry.get("label")

        if (
            roman_boundary_page is not None
            and entry_page is not None
            and entry_page <= roman_boundary_page
            and entry_label in roman_allowed
        ):
            continue

        if (
            annex_start_idx is not None
            and idx >= annex_start_idx
            and entry_label in annex_allowed
        ):
            continue

        filtered.append(issue)

    return filtered


def main() -> None:
    args = parse_args()
    llm = build_llm()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = DEFAULT_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tagger = None
    if args.reclassify and not args.reclassify_no_llm:
        tagger = _build_tagger(args.data_source)

    if args.file_id:
        points = [get_document_by_id(args.file_id, args.data_source)]
    else:
        points = load_or_select_doc_ids(
            args.records, args.data_source, args.doc_ids_path
        )

    requested = args.records if args.records else len(points)
    if len(points) < requested:
        print(f"Warning: only found {len(points)} documents with classified TOC.")

    pass_count = 0
    fail_count = 0
    mode = "a" if args.append_output else "w"
    with output_path.open(mode, encoding="utf-8") as handle, log_path.open(
        mode, encoding="utf-8"
    ) as log_handle:
        for idx, point in enumerate(points, start=1):
            payload = point.payload or {}
            doc_id = point.id
            title = (
                payload.get("title")
                or payload.get("map_title")
                or payload.get("src_title")
                or "Unknown"
            )
            raw_toc = _get_raw_toc_from_payload(payload)
            toc_text = (
                payload.get("toc_classified") or payload.get("sys_toc_classified") or ""
            )
            raw_toc_display = _indent_toc_lines(raw_toc)
            toc_text_display = _indent_toc_lines(toc_text)
            db_log = (
                f"{'=' * 80}\n"
                f"doc_id: {doc_id}\n"
                f"title: {title}\n\n"
                "DB TOC (raw):\n"
                f"{raw_toc_display.strip() or '(missing)'}\n\n"
                "DB TOC (classified):\n"
                f"{toc_text_display.strip() or '(missing)'}\n"
            )
            print(db_log, flush=True)
            log_handle.write(db_log)
            if args.reclassify_no_llm:
                entries = _reclassify_entries_no_llm(payload)
            elif tagger:
                entries = _reclassify_entries(tagger, payload)
            else:
                entries = parse_classified_toc(toc_text)
            if not entries:
                entries = parse_classified_toc(toc_text)
            if args.reclassify or args.reclassify_no_llm:
                reclassified_text = _format_classified_toc(entries)
                reclassified_log = (
                    "\nReclassified TOC:\n"
                    f"{reclassified_text.strip() or '(missing)'}\n"
                )
                print(reclassified_log, flush=True)
                log_handle.write(reclassified_log)
            total_pages = payload.get("page_count") or payload.get("sys_page_count")
            roman_boundary = compute_roman_boundary(entries, total_pages)
            annex_start_idx = compute_annex_start_index(entries)
            first_third = int(total_pages / 3) if total_pages else None

            input_payload = {
                "doc_id": doc_id,
                "title": title,
                "total_pages": total_pages,
                "first_third_page": first_third,
                "roman_boundary_page": roman_boundary,
                "annex_start_idx": annex_start_idx,
                "entries": entries,
            }
            prompt = render_prompt(input_payload)
            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = str(response.content)
            result = parse_llm_response(response_text, prompt)
            raw_issues = list(result.get("issues", []))
            filtered_issues = _filter_issues(
                raw_issues, entries, roman_boundary, annex_start_idx
            )
            result["issues"] = filtered_issues
            if not filtered_issues and result.get("verdict") == "fail":
                result["verdict"] = "pass"
                result["score"] = max(int(result.get("score") or 0), 80)
            result["raw_issues"] = raw_issues
            llm_log = (
                "\nLLM verdict: {verdict}\n"
                "LLM score: {score}\n"
                "LLM summary: {summary}\n"
                "LLM issues: {issues}\n"
            ).format(
                verdict=result.get("verdict"),
                score=result.get("score"),
                summary=result.get("summary") or "",
                issues=json.dumps(
                    result.get("issues", []), ensure_ascii=False, indent=2
                ),
            )
            print(llm_log, flush=True)
            log_handle.write(llm_log)
            result.update(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "total_pages": total_pages,
                    "roman_boundary_page": roman_boundary,
                    "annex_start_idx": annex_start_idx,
                    "entries": entries,
                }
            )
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            verdict = result.get("verdict")
            pass_count_tmp = pass_count + (1 if verdict == "pass" else 0)
            total_seen = pass_count + fail_count + 1
            print(
                f"{doc_id}: {result.get('verdict')} score={result.get('score')} "
                f"(running pass rate: {pass_count_tmp}/{total_seen})"
            )
            if result.get("verdict") == "pass":
                pass_count += 1
            elif result.get("verdict") == "fail":
                fail_count += 1

    total = pass_count + fail_count
    if total:
        print(f"Summary: {pass_count} pass, {fail_count} fail")


if __name__ == "__main__":
    main()
