"""Keep paragraph breaks and headings when retaining verified sentences."""

import re

from ui.backend.services.brief_citation_model import cited_numbers_in_order
from ui.backend.services.citation_fidelity import split_sentences

HEADING = re.compile(r"^(#{1,6})[ \t]+\S")


def numbered_sentences(answer: str, preceding_sentence: str = "") -> list[dict]:
    """Keep the reader's preceding sentence available across verification batches."""
    rows = []
    for index, sentence in enumerate(split_sentences(answer), start=1):
        row = {
            "id": index,
            "text": sentence,
            "citations": cited_numbers_in_order(sentence),
        }
        if preceding_sentence:
            row["preceding_sentence"] = preceding_sentence
        rows.append(row)
        preceding_sentence = sentence
    return rows


def _heading_stack(
    headings: list[tuple[int, str]], depth: int, approved: bool, sentence: str
) -> list[tuple[int, str]]:
    retained = [item for item in headings if item[0] < depth]
    if approved:
        retained.append((depth, sentence))
    return retained


def retain_supported_sentences(
    answer: str, sentences: list[dict], supported: set[int]
) -> str:
    parts: list[str] = []
    headings: list[tuple[int, str]] = []
    offset = 0
    newline = ""
    for row in sentences:
        sentence = row["text"]
        start = answer.index(sentence, offset)
        between = answer[offset:start]
        if "\n" in between:
            newline = "\n\n" if "\n\n" in between else newline or "\n"
        offset = start + len(sentence)
        approved = row["id"] in supported
        if match := HEADING.match(sentence):
            headings = _heading_stack(headings, len(match[1]), approved, sentence)
            continue
        if not approved:
            continue
        if parts:
            parts.append("\n\n" if headings else newline or " ")
        if headings:
            parts.append("\n\n".join(heading for _, heading in headings) + "\n\n")
            headings.clear()
        parts.append(sentence)
        newline = ""
    return "".join(parts)
