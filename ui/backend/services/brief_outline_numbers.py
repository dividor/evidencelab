"""Number template headings the same way as the Brief Central outline."""


def outline_numbers(subheadings):
    top = sub = 0
    numbers = []
    for is_subheading in subheadings:
        if is_subheading and top:
            sub += 1
            numbers.append(f"{top}.{sub}")
        else:
            top += 1
            sub = 0
            numbers.append(str(top))
    return numbers


def number_saved_sections(results):
    """Older runs saved sibling levels and section positions, before storing numbers."""
    groups = {}
    for result in results:
        output = result.actual_output or {}
        assignment = output.get("assignment") or {}
        if assignment.get("template_id") and not assignment.get("heading_number"):
            groups.setdefault(assignment["template_id"], []).append(
                (assignment, output)
            )
    for rows in groups.values():
        _number_snapshot(rows)


def _number_snapshot(rows):
    levels = {0: False}
    for assignment, output in rows:
        position = assignment["section_index"]
        if "siblings" not in output:
            continue
        children = len(assignment.get("child_headings", []))
        siblings = [s["level"] == 2 for s in output["siblings"]]
        if children:
            levels[position] = False
            siblings = siblings[:-children]
        levels.update(enumerate(siblings[:position]))
        levels.update(
            enumerate([True] * children + siblings[position:], start=position + 1)
        )
    prefix = []
    while len(prefix) in levels:
        prefix.append(levels[len(prefix)])
    numbers = outline_numbers(prefix)
    for assignment, _ in rows:
        position = assignment["section_index"]
        if 0 <= position < len(numbers):
            assignment["heading_number"] = numbers[position]
