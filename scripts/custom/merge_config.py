"""Deep-merge a customization overlay onto the base ``config.json``.

Part of the deployment customization overlay (see
``docs/deployment/customization.md``). The overlay file holds ONLY deltas; this
renders the fully-resolved config that the frontend build bundles and the API
mounts at runtime, so a deployment never copies the whole ``config.json`` and
therefore never drifts behind the base.

Merge semantics:
  * ``dict`` + ``dict``            -> recursive merge (overlay keys add/override)
  * anything + scalar             -> replaced
  * anything + list               -> replaced wholesale (lists never concatenate)
  * a key whose overlay value is ``null`` -> deleted from the base
  * an object containing ``"$replace": true`` -> replaces the whole subtree
    instead of merging (use when you need an exact set, not base + yours)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPLACE_DIRECTIVE = "$replace"


def _is_replace(node: Any) -> bool:
    """True when ``node`` is an object requesting wholesale replacement."""
    return isinstance(node, dict) and node.get(REPLACE_DIRECTIVE) is True


def _without_directive(node: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of ``node`` with the ``$replace`` directive removed."""
    return {k: copy.deepcopy(v) for k, v in node.items() if k != REPLACE_DIRECTIVE}


def deep_merge(base: Any, overlay: Any) -> Any:
    """Return a new value: ``overlay`` deep-merged onto ``base``."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return copy.deepcopy(overlay)
    if _is_replace(overlay):
        return _without_directive(overlay)
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if value is None:
            result.pop(key, None)
        elif key in result:
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_overlay(base: Dict[str, Any], overlay: Dict[str, Any]) -> None:
    """Reject overlay top-level keys that are not part of the base schema.

    A new top-level key is almost always a typo (the config schema is fixed),
    so we fail loud rather than silently bake a key nothing reads.
    """
    unknown = sorted(set(overlay) - set(base) - {REPLACE_DIRECTIVE})
    if unknown:
        allowed = ", ".join(sorted(base))
        raise ValueError(
            f"Unknown top-level key(s) in overlay: {', '.join(unknown)}. "
            f"Allowed: {allowed}."
        )


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def render(base_path: Path, overlay_path: Path) -> Dict[str, Any]:
    """Load base + overlay, validate, and return the merged config object."""
    base = _load_json(base_path)
    if not isinstance(base, dict):
        raise ValueError(f"Base config must be a JSON object: {base_path}")
    overlay = _load_json(overlay_path) if overlay_path.exists() else {}
    if not isinstance(overlay, dict):
        raise ValueError(f"Overlay must be a JSON object: {overlay_path}")
    validate_overlay(base, overlay)
    return deep_merge(base, overlay)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render config.json with a customization overlay."
    )
    parser.add_argument("--base", default="config.json", type=Path)
    parser.add_argument("--overlay", default="custom/config.overlay.json", type=Path)
    parser.add_argument("--out", default="custom/config.resolved.json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        resolved = render(args.base, args.overlay)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"merge_config: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(resolved, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"merge_config: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
