from pathlib import Path


def apply_delta(
    *,
    delta_dir: Path,
    output_dir: Path,
    base_dir_override: Path | None = None,
    xdelta3_bin: str = "xdelta3",
) -> None:
    raise RuntimeError(
        "Delta restore is not implemented in this repo. "
        "Use a full qdrant_dump_* backup or add the delta apply implementation."
    )
