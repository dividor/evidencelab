"""Number displayed Assistant citations in the order readers encounter them."""

from ui.backend.services.brief_citation_model import CITATION_RE, cited_numbers_in_order


def evidence_numbers(message: dict) -> dict[int, int]:
    """Resolve the numbers shown in one reply to its conversation evidence."""
    return {
        source["index"]: source["evidenceIndex"]
        for source in message.get("sources") or []
        if isinstance(source.get("index"), int)
        and isinstance(source.get("evidenceIndex"), int)
    }


def remap_citations(text: str, numbers: dict[int, int]) -> str:
    """Update citation markers while leaving the surrounding prose intact."""
    if not numbers:
        return text

    def replace(match):
        original = [int(value) for value in match[1].split(",")]
        return (
            "["
            + ", ".join(str(numbers.get(number, number)) for number in original)
            + "]"
        )

    return CITATION_RE.sub(replace, text)


def number_answer_citations(text: str, sources: list[dict]) -> tuple[str, list[dict]]:
    """Assign each cited passage one display number and keep its conversation index."""
    by_index = {source["index"]: source for source in sources}
    cited = [number for number in cited_numbers_in_order(text) if number in by_index]
    numbers = {number: index for index, number in enumerate(cited, start=1)}
    ordered = [
        {**by_index[number], "index": index, "evidenceIndex": number}
        for number, index in numbers.items()
    ]
    return remap_citations(text, numbers), ordered
