#!/usr/bin/env python3
"""
Train and evaluate a TOC section classifier from DB-labeled TOCs.

Workflow:
1) Sample classified TOCs from Qdrant (data source default: wfp)
2) Correct labels using tagger rules (keyword lock, hierarchy, sequence)
3) Split by document into train/test
4) Train a centroid classifier on embeddings + numeric features
5) Evaluate on test set and write metrics
6) Write train/test JSONL datasets
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
from fastembed import TextEmbedding

# Ensure we can import pipeline
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.db import Database, load_datasources_config  # noqa: E402
from pipeline.processors.tagging.tagger_constants import SECTION_TYPES  # noqa: E402
from pipeline.processors.tagging.tagger_rules import (  # noqa: E402
    apply_keyword_locking,
    apply_sequence_rules,
    propagate_hierarchy,
)
from pipeline.processors.tagging.tagger_toc import (  # noqa: E402
    normalize_title,
    parse_toc,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a TOC classifier from DB-labeled TOCs."
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="wfp",
        help="Data source/collection suffix (default: wfp)",
    )
    parser.add_argument(
        "--records",
        type=int,
        default=200,
        help="Number of documents to sample (default: 200)",
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="Random seed for sampling/split"
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="Train split ratio by document (default: 0.8)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "data" / "toc_classifier"),
        help="Output directory for datasets and model",
    )
    parser.add_argument(
        "--doc-ids-path",
        type=str,
        default=None,
        help="Optional JSON file to persist sampled document ids",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=None,
        help="Override embedding model id (default: datasource tag config)",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Skip documents that fail TOC correction instead of aborting",
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Only build corrected train/test datasets (skip training/eval)",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=32,
        help="Embedding batch size for training (default: 32)",
    )
    return parser.parse_args()


def _resolve_embedding_model(data_source: str, override: Optional[str]) -> str:
    if override:
        return override
    config = load_datasources_config()
    datasources = config.get("datasources", config)
    for key, val in datasources.items():
        if val.get("data_subdir") == data_source or key == data_source:
            tag_cfg = val.get("pipeline", {}).get("tag", {})
            model_id = tag_cfg.get("dense_model")
            if model_id:
                return model_id
    return "intfloat/multilingual-e5-large"


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
    toc_data = payload.get("sys_toc") or payload.get("toc")
    if isinstance(toc_data, str):
        return toc_data
    if isinstance(toc_data, list):
        return _format_toc_list(toc_data)
    return ""


def _payload_has_classified_toc(payload: Dict[str, Any]) -> bool:
    toc = payload.get("sys_toc_classified") or payload.get("toc_classified")
    return isinstance(toc, str) and bool(toc.strip())


def _parse_classified_toc(toc_text: str) -> List[Dict[str, Any]]:
    import re

    pattern = re.compile(
        r"^(?P<indent>\s*)\[H(?P<level>\d+)\]\s*(?P<title>.*?)\s*\|\s*(?P<label>[a-z_]+)"
        r"\s*(?:\|\s*page\s*(?P<page>\d+)\s*(?:\((?P<roman>[^)]*)\))?)?\s*$"
    )
    entries: List[Dict[str, Any]] = []
    for idx, line in enumerate(toc_text.splitlines()):
        match = pattern.match(line.strip())
        if not match:
            continue
        page = match.group("page")
        title = match.group("title").strip()
        level = int(match.group("level"))
        indentation = match.group("indent") or ""
        entries.append(
            {
                "index": idx,
                "title": title,
                "normalized_title": normalize_title(title),
                "level": level,
                "page": int(page) if page and page.isdigit() else None,
                "roman": match.group("roman").strip() if match.group("roman") else None,
                "label": match.group("label").strip(),
                "original_line": line.strip(),
                "indentation": indentation,
            }
        )
    return entries


def _build_labels_by_index(entries: List[Dict[str, Any]]) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    for entry in entries:
        label = entry.get("label") or "other"
        labels[entry["index"]] = label if label in SECTION_TYPES else "other"
    return labels


def _correct_labels(
    entries: List[Dict[str, Any]],
    labels_by_index: Dict[int, str],
    document: Dict[str, Any],
) -> Dict[int, str]:
    locked_labels = apply_keyword_locking(entries)
    merged = dict(labels_by_index)
    merged.update(locked_labels)
    propagated = propagate_hierarchy(entries=entries, labels=merged)
    corrected = apply_sequence_rules(
        entries=entries,
        labels=propagated,
        document=document,
    )
    for idx, label in list(corrected.items()):
        corrected[idx] = label if label in SECTION_TYPES else "other"
    return corrected


def _add_ancestor_context(entries: List[Dict[str, Any]]) -> None:
    stack: List[Dict[str, Any]] = []
    for entry in entries:
        level = entry.get("level") or 1
        while stack and (stack[-1].get("level") or 1) >= level:
            stack.pop()
        entry["parent_title"] = stack[-1]["title"] if stack else None
        entry["ancestor_titles"] = [node.get("title") for node in stack]
        entry["ancestor_levels"] = [node.get("level") for node in stack]
        stack.append(entry)


def _build_samples_for_document(
    doc_id: str,
    payload: Dict[str, Any],
    entries: List[Dict[str, Any]],
    labels_by_index: Dict[int, str],
) -> List[Dict[str, Any]]:
    total_pages = payload.get("page_count") or payload.get("sys_page_count")
    _add_ancestor_context(entries)
    samples: List[Dict[str, Any]] = []
    total_entries = len(entries)
    for entry in entries:
        idx = entry.get("index")
        label = labels_by_index.get(idx, "other")
        if label not in SECTION_TYPES:
            label = "other"
        title = entry.get("title") or ""
        parent_title = entry.get("parent_title")
        ancestor_titles = entry.get("ancestor_titles") or []
        ancestor_levels = entry.get("ancestor_levels") or []
        level = entry.get("level")
        page = entry.get("page")
        roman = entry.get("roman")
        position = idx / (total_entries - 1) if total_entries > 1 else 0.0
        heading_path = " > ".join([item for item in [*ancestor_titles, title] if item])
        text = f"H{level} {title}".strip()
        if heading_path:
            text = f"{text} | path: {heading_path}"
        samples.append(
            {
                "doc_id": doc_id,
                "toc_index": idx,
                "title": title,
                "parent_title": parent_title,
                "ancestor_titles": ancestor_titles,
                "ancestor_levels": ancestor_levels,
                "heading_path": heading_path,
                "level": level,
                "page": page,
                "roman": roman,
                "position": position,
                "total_pages": total_pages,
                "text": text,
                "label": label,
            }
        )
    return samples


def _sample_documents(
    db: Database,
    limit: int,
    seed: int,
    doc_ids_path: Optional[str],
) -> List[Any]:
    if doc_ids_path:
        path = Path(doc_ids_path)
        if path.exists():
            ids = json.loads(path.read_text(encoding="utf-8"))
            points: List[Any] = []
            for doc_id in ids:
                points.extend(
                    db.client.retrieve(
                        collection_name=db.documents_collection,
                        ids=[doc_id],
                        with_payload=True,
                    )
                )
            return points

    rng = random.Random(seed)
    reservoir: List[Any] = []
    seen = 0
    next_offset = None
    while True:
        points, next_offset = db.client.scroll(
            collection_name=db.documents_collection,
            limit=200,
            with_payload=True,
            offset=next_offset,
        )
        if not points:
            break
        for point in points:
            payload = point.payload or {}
            if not _payload_has_classified_toc(payload):
                continue
            seen += 1
            if len(reservoir) < limit:
                reservoir.append(point)
            else:
                j = rng.randint(0, seen - 1)
                if j < limit:
                    reservoir[j] = point
        if next_offset is None:
            break

    if doc_ids_path:
        path = Path(doc_ids_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([p.id for p in reservoir]), encoding="utf-8")
    return reservoir


def _load_entries_and_labels(
    payload: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
    toc_classified = payload.get("sys_toc_classified") or payload.get("toc_classified")
    if not isinstance(toc_classified, str) or not toc_classified.strip():
        raise ValueError("Missing sys_toc_classified in payload")

    raw_toc = _get_raw_toc_from_payload(payload)
    if not raw_toc:
        raise ValueError("Missing sys_toc in payload")

    raw_entries = parse_toc(raw_toc)
    classified_entries = _parse_classified_toc(toc_classified)
    if len(raw_entries) != len(classified_entries):
        raise ValueError(
            f"TOC length mismatch: raw={len(raw_entries)} classified={len(classified_entries)}"
        )

    labels_by_index = _build_labels_by_index(classified_entries)
    return raw_entries, labels_by_index


def _split_by_document(
    docs: List[str], train_ratio: float, seed: int
) -> Tuple[set[str], set[str]]:
    rng = random.Random(seed)
    shuffled = list(docs)
    rng.shuffle(shuffled)
    split_idx = int(len(shuffled) * train_ratio)
    return set(shuffled[:split_idx]), set(shuffled[split_idx:])


def _chunked(iterable: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def _vectorize_samples(
    samples: List[Dict[str, Any]],
    embedder: TextEmbedding,
    batch_size: int = 64,
) -> np.ndarray:
    texts = [sample["text"] for sample in samples]
    embeddings: List[np.ndarray] = []
    for batch in _chunked(texts, batch_size):
        embeddings.extend(list(embedder.embed(batch)))
    emb = np.asarray(embeddings, dtype=np.float32)

    numeric_features = []
    for sample in samples:
        level = sample.get("level") or 1
        position = sample.get("position") or 0.0
        page = sample.get("page")
        total_pages = sample.get("total_pages") or 0
        has_page = 1.0 if page is not None else 0.0
        page_norm = 0.0
        if page is not None and total_pages:
            page_norm = min(float(page) / float(total_pages), 1.0)
        level_norm = min(float(level) / 6.0, 1.0)
        roman = sample.get("roman")
        has_roman = 1.0 if roman else 0.0
        numeric_features.append([level_norm, position, has_page, page_norm, has_roman])
    numeric = np.asarray(numeric_features, dtype=np.float32)
    combined = np.concatenate([emb, numeric], axis=1)
    norms = np.linalg.norm(combined, axis=1, keepdims=True)
    combined = combined / np.clip(norms, 1e-8, None)
    return combined


def _train_centroids(
    vectors: np.ndarray, labels: List[str], label_order: List[str]
) -> np.ndarray:
    centroids = []
    for label in label_order:
        indices = [i for i, y in enumerate(labels) if y == label]
        if not indices:
            centroids.append(np.zeros(vectors.shape[1], dtype=np.float32))
            continue
        subset = vectors[indices]
        centroid = subset.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        centroids.append(centroid.astype(np.float32))
    return np.stack(centroids, axis=0)


def _predict(
    centroids: np.ndarray, vectors: np.ndarray, label_order: List[str]
) -> List[str]:
    scores = vectors @ centroids.T
    best_idx = np.argmax(scores, axis=1)
    return [label_order[i] for i in best_idx]


def _compute_metrics(
    y_true: List[str], y_pred: List[str], label_order: List[str]
) -> Dict[str, Any]:
    total = len(y_true)
    accuracy = (
        sum(1 for t, p in zip(y_true, y_pred) if t == p) / total if total else 0.0
    )

    per_label = {}
    f1s = []
    weighted_f1_sum = 0.0
    total_support = 0
    for label in label_order:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        per_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        f1s.append(f1)
        weighted_f1_sum += f1 * support
        total_support += support

    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    weighted_f1 = weighted_f1_sum / total_support if total_support else 0.0
    return {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_label": per_label,
        "total": total,
    }


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = Database(data_source=args.data_source)
    points = _sample_documents(
        db, args.records, args.seed, doc_ids_path=args.doc_ids_path
    )
    if not points:
        raise RuntimeError("No documents with classified TOCs were found.")

    samples_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for point in points:
        payload = point.payload or {}
        doc_id = str(point.id)
        try:
            entries, labels_by_index = _load_entries_and_labels(payload)
            corrected_labels = _correct_labels(
                entries=entries, labels_by_index=labels_by_index, document=payload
            )
            samples = _build_samples_for_document(
                doc_id=doc_id,
                payload=payload,
                entries=entries,
                labels_by_index=corrected_labels,
            )
            if samples:
                samples_by_doc[doc_id] = samples
        except Exception as exc:
            if args.skip_errors:
                logger.warning("Skipping doc %s: %s", doc_id, exc)
                continue
            raise

    doc_ids = list(samples_by_doc.keys())
    if not doc_ids:
        raise RuntimeError("No usable documents after TOC correction.")

    train_docs, test_docs = _split_by_document(doc_ids, args.train_ratio, args.seed)
    train_samples = [
        sample for doc_id in train_docs for sample in samples_by_doc.get(doc_id, [])
    ]
    test_samples = [
        sample for doc_id in test_docs for sample in samples_by_doc.get(doc_id, [])
    ]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "train.jsonl", train_samples)
    _write_jsonl(output_dir / "test.jsonl", test_samples)
    logger.info("Saved train.jsonl and test.jsonl to %s", output_dir)

    if args.dataset_only:
        return

    embedding_model_id = _resolve_embedding_model(
        args.data_source, args.embedding_model
    )
    logger.info("Using embedding model: %s", embedding_model_id)
    embedder = TextEmbedding(model_name=embedding_model_id)

    label_order = list(SECTION_TYPES)
    train_vectors = _vectorize_samples(
        train_samples, embedder, batch_size=args.embedding_batch_size
    )
    test_vectors = _vectorize_samples(
        test_samples, embedder, batch_size=args.embedding_batch_size
    )
    train_labels = [sample["label"] for sample in train_samples]
    test_labels = [sample["label"] for sample in test_samples]

    centroids = _train_centroids(train_vectors, train_labels, label_order)
    predictions = _predict(centroids, test_vectors, label_order)

    metrics = _compute_metrics(test_labels, predictions, label_order)
    metrics.update(
        {
            "data_source": args.data_source,
            "records_requested": args.records,
            "documents_used": len(samples_by_doc),
            "train_docs": len(train_docs),
            "test_docs": len(test_docs),
            "train_samples": len(train_samples),
            "test_samples": len(test_samples),
            "embedding_model": embedding_model_id,
        }
    )

    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    model_path = output_dir / "centroids.npz"
    np.savez(
        model_path,
        centroids=centroids,
        label_order=np.array(label_order),
        embedding_model=embedding_model_id,
        numeric_features=np.array(
            ["level_norm", "position", "has_page", "page_norm", "has_roman"]
        ),
    )

    logger.info("Saved metrics to %s", output_dir / "metrics.json")
    logger.info("Saved model to %s", model_path)
    logger.info(
        "Accuracy: %.3f | Macro F1: %.3f",
        metrics["accuracy"],
        metrics["macro_f1"],
    )


if __name__ == "__main__":
    main()
