#!/usr/bin/env python3
"""
Compute code complexity metrics for pipeline, ui, and utils.

Metrics:
- Cyclomatic complexity (lizard)
- Cognitive complexity (Python via cognitive_complexity, JS/TS via ESLint sonarjs rule)
- Maintainability Index (radon, Python only)
"""

import argparse
import ast
import json
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Sequence, cast

import lizard
from cognitive_complexity.api import get_cognitive_complexity
from radon.metrics import mi_rank, mi_visit

DEFAULT_ROOTS = [
    Path("pipeline"),
    Path("utils"),
    Path("ui"),
]

LANGUAGE_EXTS = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".ts", ".tsx"},
}

DEFAULT_EXCLUDE_DIRS = {
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "integration",
}


@dataclass(frozen=True)
class FileMetrics:
    path: str
    language: str
    nloc: int
    function_count: int
    cyclomatic_avg: float
    cyclomatic_max: int
    cognitive_avg: float | None
    cognitive_max: int | None
    mi: float | None
    mi_rank: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate cyclomatic/cognitive complexity and maintainability index."
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[str(path) for path in DEFAULT_ROOTS],
        help="Paths to analyze (default: pipeline utils ui/frontend/src)",
    )
    parser.add_argument(
        "--exclude-dir",
        nargs="*",
        default=sorted(DEFAULT_EXCLUDE_DIRS),
        help="Directory names to exclude",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top files to show in text output (default: 20)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON output to a file",
    )
    parser.add_argument(
        "--skip-js-cognitive",
        action="store_true",
        help="Skip JS/TS cognitive complexity (no Node.js required)",
    )
    parser.add_argument(
        "--fail-on-bad",
        action="store_true",
        help="Exit non-zero if any file rates as bad for any metric",
    )
    return parser.parse_args()


def normalize_language(path: Path) -> str | None:
    suffix = path.suffix.lower()
    for language, exts in LANGUAGE_EXTS.items():
        if suffix in exts:
            return language
    return None


def should_skip(path: Path, exclude_dirs: set[str]) -> bool:
    return any(part in exclude_dirs for part in path.parts)


def discover_files(paths: Sequence[str], exclude_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    for root_str in paths:
        root = Path(root_str)
        if root.is_file():
            language = normalize_language(root)
            if language and not should_skip(root, exclude_dirs):
                files.append(root)
            continue
        if not root.exists():
            raise FileNotFoundError(f"Path does not exist: {root}")
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if should_skip(path, exclude_dirs):
                continue
            if normalize_language(path):
                files.append(path)
    return sorted(files)


def compute_python_cognitive_by_file(paths: Sequence[Path]) -> dict[str, list[int]]:
    results: dict[str, list[int]] = {}
    for path in paths:
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise RuntimeError(f"Failed to parse Python file: {path}") from exc

        values: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                values.append(get_cognitive_complexity(node))
        results[str(path)] = values
    return results


def compute_js_metrics_by_file(
    paths: Sequence[Path],
    eslint_cwd: Path,
    repo_root: Path,
    include_cognitive: bool,
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    if not paths:
        return {}, {}

    plugin_section = 'plugins: ["sonarjs"],' if include_cognitive else ""
    cognitive_rule = (
        '"sonarjs/cognitive-complexity": ["error", 0],' if include_cognitive else ""
    )

    node_script = """
const { ESLint } = require("eslint");

(async () => {
  const files = JSON.parse(process.argv[1]);
  const eslint = new ESLint({
    useEslintrc: false,
    overrideConfig: {
      parser: "@typescript-eslint/parser",
      parserOptions: {
        ecmaVersion: 2020,
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
      __PLUGIN_SECTION__
      rules: {
        __COGNITIVE_RULE__
        "complexity": ["error", 0],
      },
    },
  });

  const results = await eslint.lintFiles(files);
  const output = { cognitive: {}, cyclomatic: {} };

  for (const result of results) {
    const cognitiveValues = [];
    const cyclomaticValues = [];
    for (const message of result.messages) {
      if (message.ruleId === "sonarjs/cognitive-complexity") {
        if (message.data && message.data.complexity !== undefined) {
          cognitiveValues.push(Number(message.data.complexity));
          continue;
        }
        const match = message.message.match(/Cognitive Complexity from (\\d+)/);
        if (match) {
          cognitiveValues.push(Number(match[1]));
        }
      }

      if (message.ruleId === "complexity") {
        if (message.data && message.data.complexity !== undefined) {
          cyclomaticValues.push(Number(message.data.complexity));
          continue;
        }
        const match = message.message.match(/complexity of (\\d+)/i);
        if (match) {
          cyclomaticValues.push(Number(match[1]));
        }
      }
    }
    output.cognitive[result.filePath] = cognitiveValues;
    output.cyclomatic[result.filePath] = cyclomaticValues;
  }

  console.log(JSON.stringify(output));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    node_script = node_script.replace("__PLUGIN_SECTION__", plugin_section).replace(
        "__COGNITIVE_RULE__", cognitive_rule
    )

    eslint_root = eslint_cwd.resolve()
    eslint_files = []
    for path in paths:
        resolved = path.resolve()
        try:
            eslint_files.append(str(resolved.relative_to(eslint_root)))
        except ValueError:
            eslint_files.append(str(resolved))

    try:
        result = subprocess.run(
            ["node", "-e", node_script, json.dumps(eslint_files)],
            cwd=eslint_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Node.js is required to compute JS/TS complexity metrics. "
            "Install Node and re-run the metrics script."
        ) from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(
            "ESLint execution failed while computing JS/TS complexity metrics. "
            "Run `npm install` in ui/frontend to install ESLint dependencies. "
            f"{message}"
        ) from exc

    def normalize_key(path_value: str) -> str:
        path_obj = Path(path_value)
        if not path_obj.is_absolute():
            path_obj = (eslint_cwd / path_obj).resolve()
        else:
            path_obj = path_obj.resolve()
        try:
            return str(path_obj.relative_to(repo_root))
        except ValueError:
            return str(path_obj)

    try:
        parsed = json.loads(result.stdout)
        cognitive = {
            normalize_key(key): value
            for key, value in parsed.get("cognitive", {}).items()
        }
        cyclomatic = {
            normalize_key(key): value
            for key, value in parsed.get("cyclomatic", {}).items()
        }
        return cognitive, cyclomatic
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Failed to parse ESLint output for JS/TS complexity metrics."
        ) from exc


def compute_python_mi(source: str) -> tuple[float, str]:
    score = mi_visit(source, multi=True)
    return score, mi_rank(score)


def average(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return statistics.fmean(values)


def build_file_metrics(
    path: Path,
    cognitive_map: dict[str, list[int] | None],
    cyclomatic_map: dict[str, list[int]] | None,
) -> FileMetrics:
    analysis = lizard.analyze_file(str(path))
    cyclomatic_override = cyclomatic_map.get(str(path)) if cyclomatic_map else None
    if cyclomatic_override is None:
        cyclomatic_values = [
            func.cyclomatic_complexity for func in analysis.function_list
        ]
        function_count = len(analysis.function_list)
    else:
        cyclomatic_values = cyclomatic_override
        function_count = len(cyclomatic_values)
    cognitive_values = cognitive_map.get(str(path), [])

    mi_score = None
    mi_grade = None
    if normalize_language(path) == "python":
        source = path.read_text(encoding="utf-8")
        mi_score, mi_grade = compute_python_mi(source)

    if cognitive_values is None:
        cognitive_avg = None
        cognitive_max = None
    else:
        cognitive_avg = average(cognitive_values)
        cognitive_max = max(cognitive_values) if cognitive_values else 0

    return FileMetrics(
        path=str(path),
        language=normalize_language(path) or "unknown",
        nloc=analysis.nloc,
        function_count=function_count,
        cyclomatic_avg=average(cyclomatic_values),
        cyclomatic_max=max(cyclomatic_values) if cyclomatic_values else 0,
        cognitive_avg=cognitive_avg,
        cognitive_max=cognitive_max,
        mi=mi_score,
        mi_rank=mi_grade,
    )


def group_key(path: str, roots: Sequence[str]) -> str:
    normalized = path.replace("\\", "/")
    for root in roots:
        root_norm = root.replace("\\", "/").rstrip("/")
        if normalized.startswith(root_norm + "/") or normalized == root_norm:
            return root_norm
    return "other"


def summarize(metrics: list[FileMetrics], roots: Sequence[str]) -> dict[str, dict]:
    grouped: dict[str, list[FileMetrics]] = {root: [] for root in roots}
    grouped["other"] = []
    for item in metrics:
        grouped[group_key(item.path, roots)].append(item)

    summary: dict[str, dict] = {}
    for key, items in grouped.items():
        if not items:
            summary[key] = {
                "files": 0,
                "nloc": 0,
                "cyclomatic_avg": 0.0,
                "cyclomatic_max": 0,
                "cognitive_avg": 0.0,
                "cognitive_max": 0,
                "mi_avg": None,
            }
            continue

        mi_values = [item.mi for item in items if item.mi is not None]
        cognitive_values = [
            item.cognitive_avg for item in items if item.cognitive_avg is not None
        ]
        cognitive_max_values = [
            item.cognitive_max for item in items if item.cognitive_max is not None
        ]
        summary[key] = {
            "files": len(items),
            "nloc": sum(item.nloc for item in items),
            "cyclomatic_avg": average(
                [item.cyclomatic_avg for item in items if item.function_count > 0]
            ),
            "cyclomatic_max": max(item.cyclomatic_max for item in items),
            "cognitive_avg": (
                statistics.fmean(cognitive_values) if cognitive_values else None
            ),
            "cognitive_max": (
                max(cognitive_max_values) if cognitive_max_values else None
            ),
            "mi_avg": statistics.fmean(mi_values) if mi_values else None,
        }
    return summary


def to_json(metrics: list[FileMetrics], summary: dict[str, dict]) -> dict:
    return {
        "summary": summary,
        "files": [item.__dict__ for item in metrics],
    }


def collect_bad_files(metrics: list[FileMetrics]) -> list[dict[str, object]]:
    bad_files: list[dict[str, object]] = []
    for item in metrics:
        reasons: list[str] = []
        cc_rating = rate_cc(item.cyclomatic_max)
        if cc_rating == "bad":
            reasons.append("cyclomatic")
        if item.cognitive_max is not None and rate_cog(item.cognitive_max) == "bad":
            reasons.append("cognitive")
        if item.mi is not None and rate_mi(item.mi) == "bad":
            reasons.append("maintainability")
        if reasons:
            bad_files.append(
                {
                    "path": item.path,
                    "reasons": reasons,
                    "cyclomatic_max": item.cyclomatic_max,
                    "cognitive_max": item.cognitive_max,
                    "mi": item.mi,
                }
            )
    return bad_files


def render_bad_files(bad_files: list[dict[str, object]]) -> str:
    rows: list[Sequence[str]] = [
        ["File", "Bad metrics", "CC max", "Cog max", "MI"],
    ]
    for item in bad_files:
        reasons = cast(list[str], item["reasons"])
        rows.append(
            [
                str(item["path"]),
                ", ".join(reasons),
                str(item["cyclomatic_max"]),
                (
                    str(item["cognitive_max"])
                    if item["cognitive_max"] is not None
                    else "n/a"
                ),
                f"{item['mi']:.2f}" if item["mi"] is not None else "n/a",
            ]
        )
    return "\n".join(["", "Bad files (must fix)", format_table(rows)])


def format_table(rows: list[Sequence[str]]) -> str:
    widths = [max(len(cell) for cell in column) for column in zip(*rows)]
    lines = []
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))
    return "\n".join(lines)


def render_text(
    metrics: list[FileMetrics],
    summary: dict[str, dict],
    roots: Sequence[str],
    top: int,
) -> str:
    lines = []
    lines.append("Summary")
    rows: list[Sequence[str]] = [
        [
            "Path",
            "Files",
            "NLOC",
            "CC avg",
            "CC max",
            "CC rating",
            "Cog avg",
            "Cog max",
            "Cog rating",
            "MI avg",
            "MI rating",
        ]
    ]
    for root in roots:
        data = summary[root]
        cc_rating = rate_cc(data["cyclomatic_max"])
        cog_rating = rate_cog(data["cognitive_max"])
        mi_rating = rate_mi(data["mi_avg"])
        rows.append(
            [
                root,
                str(data["files"]),
                str(data["nloc"]),
                f"{data['cyclomatic_avg']:.2f}",
                str(data["cyclomatic_max"]),
                cc_rating,
                (
                    f"{data['cognitive_avg']:.2f}"
                    if data["cognitive_avg"] is not None
                    else "n/a"
                ),
                (
                    str(data["cognitive_max"])
                    if data["cognitive_max"] is not None
                    else "n/a"
                ),
                cog_rating,
                f"{data['mi_avg']:.2f}" if data["mi_avg"] is not None else "n/a",
                mi_rating,
            ]
        )
    lines.append(format_table(rows))

    if metrics:
        sorted_cc = sorted(metrics, key=lambda item: item.cyclomatic_max, reverse=True)
        cognitive_items = [item for item in metrics if item.cognitive_max is not None]
        sorted_cog = sorted(
            cognitive_items, key=lambda item: item.cognitive_max, reverse=True
        )
        sorted_mi = sorted(
            [item for item in metrics if item.mi is not None],
            key=lambda item: item.mi,
        )

        lines.append("")
        lines.append(f"Top {top} files by cyclomatic complexity")
        rows = [
            ["File", "CC max", "CC rating", "CC avg", "Cog max", "MI"],
        ]
        for item in sorted_cc[:top]:
            rows.append(
                [
                    item.path,
                    str(item.cyclomatic_max),
                    rate_cc(item.cyclomatic_max),
                    f"{item.cyclomatic_avg:.2f}",
                    (
                        str(item.cognitive_max)
                        if item.cognitive_max is not None
                        else "n/a"
                    ),
                    f"{item.mi:.2f}" if item.mi is not None else "n/a",
                ]
            )
        lines.append(format_table(rows))

        if sorted_cog:
            lines.append("")
            lines.append(f"Top {top} files by cognitive complexity")
            rows = [
                ["File", "Cog max", "Cog rating", "Cog avg", "CC max", "MI"],
            ]
            for item in sorted_cog[:top]:
                rows.append(
                    [
                        item.path,
                        (
                            str(item.cognitive_max)
                            if item.cognitive_max is not None
                            else "n/a"
                        ),
                        rate_cog(item.cognitive_max),
                        (
                            f"{item.cognitive_avg:.2f}"
                            if item.cognitive_avg is not None
                            else "n/a"
                        ),
                        str(item.cyclomatic_max),
                        f"{item.mi:.2f}" if item.mi is not None else "n/a",
                    ]
                )
            lines.append(format_table(rows))

        if sorted_mi:
            lines.append("")
            lines.append(f"Lowest {top} MI (Python only)")
            rows = [["File", "MI", "MI rating", "Rank", "CC max", "Cog max"]]
            for item in sorted_mi[:top]:
                rows.append(
                    [
                        item.path,
                        f"{item.mi:.2f}",
                        rate_mi(item.mi),
                        item.mi_rank or "n/a",
                        str(item.cyclomatic_max),
                        str(item.cognitive_max),
                    ]
                )
            lines.append(format_table(rows))

    lines.append("")
    lines.append("Guidelines")
    lines.append(
        format_table(
            [
                ["Metric", "Good", "Okay", "Bad"],
                ["Cyclomatic (CC)", "1-10", "11-20", "21+"],
                ["Cognitive (Cog)", "0-10", "11-20", "21+"],
                ["Maintainability (MI)", ">= 20 (A)", "10-19 (B)", "< 10 (C)"],
            ]
        )
    )

    return "\n".join(lines)


def ensure_js_cognitive_requirements(root: Path, require_sonarjs: bool) -> None:
    if which("node") is None:
        raise RuntimeError(
            "JS/TS complexity metrics require Node.js. "
            "Make sure `node` is on PATH (inside your .venv shell)."
        )

    node_modules = root / "node_modules"
    required = [
        node_modules / "eslint" / "package.json",
        node_modules / "@typescript-eslint" / "parser" / "package.json",
    ]
    if require_sonarjs:
        required.append(node_modules / "eslint-plugin-sonarjs" / "package.json")
    missing = [path for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "JS/TS complexity metrics require frontend dev dependencies. "
            "Run `npm install` in ui/frontend."
        )


def rate_cc(value: int) -> str:
    if value <= 10:
        return "good"
    if value <= 20:
        return "okay"
    return "bad"


def rate_cog(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value <= 10:
        return "good"
    if value <= 20:
        return "okay"
    return "bad"


def rate_mi(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 20:
        return "good"
    if value >= 10:
        return "okay"
    return "bad"


def main() -> int:
    args = parse_args()
    exclude_dirs = set(args.exclude_dir)
    files = discover_files(args.paths, exclude_dirs)
    python_files = [path for path in files if normalize_language(path) == "python"]
    js_files = [path for path in files if normalize_language(path) == "javascript"]

    cognitive_map: dict[str, list[int] | None] = {}
    cognitive_map.update(compute_python_cognitive_by_file(python_files))

    cyclomatic_map: dict[str, list[int]] | None = {}

    if js_files:
        eslint_root = Path("ui/frontend")
        if args.skip_js_cognitive and which("node") is None:
            for path in js_files:
                cognitive_map[str(path)] = None
                cyclomatic_map[str(path)] = []
        else:
            if not eslint_root.exists():
                raise RuntimeError(
                    "ui/frontend directory not found for JS/TS complexity metrics."
                )
            ensure_js_cognitive_requirements(
                eslint_root, require_sonarjs=not args.skip_js_cognitive
            )
            js_cognitive, js_cyclomatic = compute_js_metrics_by_file(
                js_files,
                eslint_root,
                Path.cwd(),
                include_cognitive=not args.skip_js_cognitive,
            )
            if args.skip_js_cognitive:
                for path in js_files:
                    cognitive_map[str(path)] = None
            else:
                cognitive_map.update(js_cognitive)
            cyclomatic_map.update(js_cyclomatic)

    metrics = [
        build_file_metrics(path, cognitive_map, cyclomatic_map) for path in files
    ]
    summary = summarize(metrics, args.paths)
    bad_files = collect_bad_files(metrics)

    if args.format == "json" or args.output:
        payload = to_json(metrics, summary)
        payload["bad_files"] = bad_files
        payload["has_bad_files"] = bool(bad_files)
        output = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        else:
            print(output)
        if args.fail_on_bad and bad_files:
            print(
                f"Found {len(bad_files)} file(s) with bad metrics.",
                file=sys.stderr,
            )
            return 1
        return 0

    report = render_text(metrics, summary, args.paths, args.top)
    if bad_files:
        report = f"{report}{render_bad_files(bad_files)}"
    print(report)
    if args.fail_on_bad and bad_files:
        print(
            f"Found {len(bad_files)} file(s) with bad metrics.",
            file=sys.stderr,
        )
        return 1
    return 0


def run() -> int:
    try:
        return main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
