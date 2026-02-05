"""TOC formatting helpers."""


def format_toc_comparison(original: str, corrected: str, width: int = 80) -> str:
    """Format two TOC strings side by side with fixed width, preserving indentation."""
    orig_lines = original.splitlines() if original else []
    corr_lines = corrected.splitlines() if corrected else []

    max_lines = max(len(orig_lines), len(corr_lines))
    output = []

    header_sep = " | "
    total_width = width * 2 + len(header_sep)
    output.append(f"{'Original TOC':<{width}}{header_sep}{'Corrected TOC':<{width}}")
    output.append("-" * total_width)

    for i in range(max_lines):
        o_line = orig_lines[i] if i < len(orig_lines) else ""
        c_line = corr_lines[i] if i < len(corr_lines) else ""

        if len(o_line) > width:
            o_fmt = o_line[: width - 3] + "..."
        else:
            o_fmt = o_line.ljust(width)

        if len(c_line) > width:
            c_fmt = c_line[: width - 3] + "..."
        else:
            c_fmt = c_line.ljust(width)

        output.append(f"{o_fmt}{header_sep}{c_fmt}")

    return "\n".join(output)
