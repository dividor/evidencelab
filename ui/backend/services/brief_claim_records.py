"""Project the factual grades of a pinned Brief into document and export views."""

from types import SimpleNamespace
from uuid import uuid5

from ui.backend.services.citation_fidelity import CitedPassage

SOURCE_FIELDS = (
    "index",
    "title",
    "page",
    "headings",
    "text",
    "sourceId",
    "chunkId",
    "docId",
    "pdfUrl",
    "reportUrl",
    "agentIndices",
    "runId",
)


def uses_claim_records(check):
    return bool(
        (getattr(check, "summary_stats", None) or {}).get("claim_record_version") == 1
    )


def _claims(section):
    evidence = section["brief_evidence"]
    return [c for p in evidence["paragraphs"] for c in p] if evidence else []


def _factual(section):
    return next(a for a in section["assertion_results"] if a["type"] == "brief_factual")


def bind_claims(section, version_id, offset):
    """Give each grade and its evidence the same immutable identity before saving."""
    claims = _claims(section)
    if not claims:
        return
    check = _factual(section)
    grades = {g["claim"]: g for g in check.get("claim_grades", [])}
    if not grades and check.get("error"):
        grades = {
            n: dict(
                claim=n,
                error=True,
                outcome="grading_error",
                verdict="cannot_assess",
                reason=check["message"],
            )
            for n in range(1, len(claims) + 1)
        }
    if len(check.get("claim_grades") or grades) != len(grades) or set(grades) != set(
        range(1, len(claims) + 1)
    ):
        raise ValueError("Factual grades do not match the pinned section's claims.")
    for n, claim in enumerate(claims, 1):
        key = str(uuid5(version_id, f"{section['section_id']}/{n}"))
        claim["claim_id"] = key
        grades[n].update(claim_id=key, passage_id=offset + n)
    check["claim_grades"] = [grades[n] for n in sorted(grades)]


def _passage(section, claim):
    sources = section["actual_output"]["sources"]
    references = section["brief_evidence"]["references"]
    passage = CitedPassage(
        section["heading"], "".join(p["text"] for p in claim["parts"]), []
    )
    for index in claim["references"]:
        ref = references[index]
        number = int(ref["label"].lstrip("?"))
        if not ref["label"].startswith("?"):
            passage.citation_indices.append(number)
        if ref["source_position"] is None:
            passage.missing_indices.append(number)
        else:
            passage.sources.append(sources[ref["source_position"]])
    return passage


def claim_passages(sections, passage_id=None):
    """Resolve by saved claim ID. Never match a judgement by list order or prose."""
    from ui.backend.services.citation_check_runner import passage_record

    for section in sections:
        claims = {c["claim_id"]: c for c in _claims(section)}
        for grade in _factual(section).get("claim_grades", []):
            pid = grade["passage_id"]
            if passage_id is not None and pid != passage_id:
                continue
            claim = claims[grade["claim_id"]]
            passage = _passage(section, claim)
            decision = dict(
                verdict=grade["verdict"],
                explanation=grade["reason"],
                problems=grade.get("unmet", []),
                confidence=None,
                supporting_quotes=grade.get("supporting_quotes", []),
            )
            row = passage_record(
                pid,
                passage,
                decision,
                error=grade["reason"] if grade.get("error") else None,
            )
            row.update(
                id=grade["claim_id"],
                score=grade.get("score"),
                passed=grade.get("passed"),
                section_id=section["section_id"],
                claim_number=grade["claim"],
                outcome=grade.get(
                    "outcome", "grading_error" if grade.get("error") else "assessed"
                ),
            )
            yield section["section_id"], passage, row


def check_rows(check):
    if uses_claim_records(check):
        return [row for _, _, row in claim_passages(check.section_results)]
    from ui.backend.schemas.testing import BriefCitationCheckPassageRead

    return [
        BriefCitationCheckPassageRead.model_validate(p).model_dump()
        for p in check.passages
    ]


def checked_pairs(check):
    return [
        (sid, p, SimpleNamespace(**row))
        for sid, p, row in claim_passages(check.section_results)
    ]
