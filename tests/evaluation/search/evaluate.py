import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage
from tabulate import tabulate

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from pipeline.db import SUPPORTED_LLMS, UI_MODEL_COMBOS  # noqa: E402
from utils.llm_factory import get_llm  # noqa: E402

load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("search_eval")

# Setup Jinja2
PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"
jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
tmpl_judge = jinja_env.get_template("search_evals_judge_relevance_user.j2")


def search_api(
    query: str,
    limit: int = 5,
    model: str = None,
    rerank: bool = False,
    rerank_model: str = None,
    sparse_model: str = None,
    api_url: str = "http://localhost:8000",
) -> List[Dict[str, Any]]:
    """Call the Search API."""
    params = {
        "q": query,
        "limit": limit,
        "rerank": str(rerank).lower(),  # httpx boolean conversion safety
    }
    if model:
        params["model"] = model
    if rerank_model:
        params["rerank_model"] = rerank_model
    if sparse_model:
        params["sparse_model"] = sparse_model

    # Detect if API key is needed (basic check)
    headers = {}
    api_key = os.environ.get("API_SECRET_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        url = f"{api_url}/search"
        logger.debug(f"Requesting {url} with params={params}")
        response = httpx.get(url, params=params, headers=headers, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except httpx.RequestError as e:
        logger.error(f"API Connection Error: {e}")
        print(f"❌ Could not connect to API at {api_url}. Is it running?")
        return []
    except httpx.HTTPStatusError as e:
        logger.error(f"API Error {e.response.status_code}: {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Unexpected API Error: {e}")
        return []


def evaluate_query(
    llm,
    query_data,
    top_k=5,
    dense_model=None,
    rerank=False,
    rerank_model=None,
    sparse_model=None,
    api_url=None,
) -> Tuple[float, List[int], List[Dict[str, Any]]]:
    query = query_data["query"]
    print(f"\nEvaluating Query: {query}")

    # Run Search via API
    results = search_api(
        query,
        limit=top_k,
        model=dense_model,
        rerank=rerank,
        rerank_model=rerank_model,
        sparse_model=sparse_model,
        api_url=api_url,
    )

    if not results:
        print("  -> No results returned (or API error).")
        return 0, 0, []

    scores = []
    details = []

    for i, res in enumerate(results):
        snippet = res.get("text", "")
        # API returns 'document_title' or 'title' in results
        title = res.get("document_title") or res.get("title") or "Unknown"

        # Judge
        content = tmpl_judge.render(query=query, title=title, snippet=snippet)
        try:
            resp = llm.invoke([HumanMessage(content=content)])
            resp_text = resp.content.strip()

            # Parse text format
            lines = resp_text.split("\n")
            score = 0
            reason = ""

            for line in lines:
                line = line.strip()
                if line.upper().startswith("SCORE:"):
                    try:
                        score_str = line.split(":", 1)[1].strip()
                        # Handle potential trails like "8/10"
                        if "/" in score_str:
                            score_str = score_str.split("/")[0]
                        score = int(score_str)
                    except Exception:
                        pass
                elif line.upper().startswith("REASON:"):
                    reason = line.split(":", 1)[1].strip()

            # Fallback if reason not captured effectively but present
            if not reason and "REASON:" in resp_text.upper():
                parts = resp_text.upper().split("REASON:", 1)
                if len(parts) > 1:
                    reason = resp_text[len(parts[0]) + 7 :].strip()

            if not reason:
                reason = "No reasoning provided."

        except Exception as e:
            logger.warning(f"Judge failed: {e}. Response: {resp_text[:200]}...")
            score = 0
            reason = "Judge Error"

        scores.append(score)
        details.append(
            {
                "rank": i + 1,
                "score": score,
                "reason": reason,
                "snippet": snippet[:100] + "...",
            }
        )
        print(f"  Result {i+1}: Score {score}/10 - {reason}")

    avg_score = sum(scores) / len(scores) if scores else 0
    print(f"  -> Avg Score: {avg_score:.1f}")

    return avg_score, scores, details


def main():
    # Detect default API URL based on environment
    # If running in Docker (usually set by user or standard checking), default to 'http://api:8000'
    # Otherwise localhost.
    default_url = os.environ.get("API_URL", "http://localhost:8000")
    if os.environ.get("DOCKER_CONTAINER"):  # Example flag if set
        default_url = "http://api:8000"

    parser = argparse.ArgumentParser(
        description="Evaluate search quality using LLM judge via API."
    )
    parser.add_argument(
        "--test-file", default="tests/evaluation/search/search_test_dataset.json"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--model", type=str, default=None, help="Dense embedding model name (optional)"
    )
    parser.add_argument(
        "--model-combo",
        type=str,
        default=None,
        help="Model combo name (optional; overrides --model)",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Judge LLM model key or name (defaults to LLM_MODEL or first supported LLM)",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        default=False,
        help="Enable reranking (default: False)",
    )
    parser.add_argument(
        "--api-url",
        default=default_url,
        help=f"API URL (default: {default_url})",
    )
    args = parser.parse_args()

    # Load Data
    fpath = Path(args.test_file)
    if not fpath.exists():
        print(f"Test file not found: {fpath}")
        sys.exit(1)

    with open(fpath, "r") as f:
        tests = json.load(f)

    # Initialize LLM (Judge)
    try:
        judge_model = (
            args.judge_model
            or os.environ.get("LLM_MODEL")
            or (next(iter(SUPPORTED_LLMS), None))
        )
        if not judge_model:
            raise ValueError(
                "No judge model configured. Set --judge-model or LLM_MODEL, "
                "or add supported_llms in config.json."
            )
        # Note: This still requires local LLM setup or API key for the Judge
        llm = get_llm(model=judge_model, temperature=0.0)
    except Exception as e:
        print(f"Failed to init Judge LLM: {e}")
        sys.exit(1)

    total_query_scores = []
    report_rows = []

    print(f"Starting evaluation on {len(tests)} queries...")
    print(f"Target API: {args.api_url}")
    if args.model_combo:
        print(f"Model Combo: {args.model_combo}")
    elif args.model:
        print(f"Model: {args.model}")
    print(f"Reranking: {args.rerank}")

    combo_list = []
    if args.model_combo:
        combo_config = UI_MODEL_COMBOS.get(args.model_combo)
        if not combo_config:
            print(
                f"Model combo not found: {args.model_combo}. "
                f"Available: {', '.join(UI_MODEL_COMBOS.keys())}"
            )
            sys.exit(1)
        combo_list = [(args.model_combo, combo_config)]
    elif UI_MODEL_COMBOS:
        combo_list = list(UI_MODEL_COMBOS.items())
    else:
        combo_list = []

    if combo_list:
        rerank_modes = [args.rerank] if args.rerank else [False, True]
        for combo_name, combo_config in combo_list:
            dense_model = combo_config.get("embedding_model")
            sparse_model = combo_config.get("sparse_model")
            if not dense_model:
                print(f"Combo '{combo_name}' missing embedding_model, skipping.")
                continue

            for rerank_enabled in rerank_modes:
                rerank_model = (
                    combo_config.get("reranker_model") if rerank_enabled else None
                )
                mode_label = "rerank" if rerank_enabled else "no-rerank"
                run_scores = []
                run_rows = []

                print(
                    f"\n--- Running combo: {combo_name} "
                    f"(model={dense_model}, mode={mode_label}) ---"
                )
                for i, test in enumerate(tests):
                    avg_score, scores, _ = evaluate_query(
                        llm,
                        test,
                        top_k=args.top_k,
                        dense_model=dense_model,
                        rerank=rerank_enabled,
                        rerank_model=rerank_model,
                        sparse_model=sparse_model,
                        api_url=args.api_url,
                    )
                    run_scores.append(avg_score)
                    run_rows.append(
                        [
                            combo_name,
                            mode_label,
                            i + 1,
                            test["query"][:60] + "...",
                            f"{avg_score:.1f}",
                            str(scores),
                        ]
                    )

                overall_avg = sum(run_scores) / len(run_scores) if run_scores else 0
                print("\n" + "=" * 80)
                print(f"SEARCH EVALUATION REPORT ({combo_name} / {mode_label})")
                print("=" * 80)
                print(
                    tabulate(
                        run_rows,
                        headers=[
                            "Combo",
                            "Mode",
                            "#",
                            "Query",
                            "Avg Score (0-10)",
                            "Scores @ 5",
                        ],
                    )
                )
                print("-" * 80)
                print("OVERALL AVERAGE RELEVANCE SCORE: " f"{overall_avg:.2f} / 10")
                print("=" * 80)
    else:
        for i, test in enumerate(tests):
            avg_score, scores, _ = evaluate_query(
                llm,
                test,
                top_k=args.top_k,
                dense_model=args.model,
                rerank=args.rerank,
                api_url=args.api_url,
            )
            total_query_scores.append(avg_score)

            report_rows.append(
                [i + 1, test["query"][:60] + "...", f"{avg_score:.1f}", str(scores)]
            )

    # Summary (single report for non-combo runs)
    if not combo_list:
        overall_avg = (
            sum(total_query_scores) / len(total_query_scores)
            if total_query_scores
            else 0
        )

        print("\n" + "=" * 80)
        print("SEARCH EVALUATION REPORT")
        print("=" * 80)
        print(
            tabulate(
                report_rows,
                headers=["#", "Query", "Avg Score (0-10)", "Scores @ 5"],
            )
        )
        print("-" * 80)
        print(f"OVERALL AVERAGE RELEVANCE SCORE: {overall_avg:.2f} / 10")
        print("=" * 80)


if __name__ == "__main__":
    main()
