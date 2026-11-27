"""Link a judge's quoted repetition to the two sections saved with the run."""

import re

from pydantic import BaseModel, Field, ValidationInfo, model_validator


class RepeatedFinding(BaseModel):
    new_clause: str = Field(min_length=1)
    existing_clause: str = Field(min_length=1)
    other_heading: str = Field(min_length=1)
    assessment: str = Field(min_length=1)

    def evidence(self, output):
        if self.new_clause in output["summary"]:
            for index, section in enumerate(output["siblings"]):
                if section["title"] == self.other_heading and self.existing_clause in (
                    section.get("content") or ""
                ):
                    return {
                        "source_index": index,
                        "source_quote": self.existing_clause,
                        "target_quote": self.new_clause,
                        "assessment": self.assessment,
                    }
        raise ValueError(
            "Quote verbatim from the new draft and the named other section."
        )


class OverlapVerdict(BaseModel):
    reason: str = Field(min_length=1)
    repeats: list[RepeatedFinding]

    @model_validator(mode="after")
    def verify_quotes(self, info: ValidationInfo):
        for match in self.repeats:
            match.evidence(info.context)
        return self

    @property
    def score(self) -> float:
        return float(not self.repeats)


def _saved_pairs(message, output):
    """Older verdicts appended verified pairs after one overall assessment."""
    siblings = output.get("siblings") or []
    titles = sorted(
        {s["title"] for s in siblings if s.get("title")}, key=len, reverse=True
    )
    if not titles:
        return {}
    title = "|".join(re.escape(t) for t in titles)
    pattern = rf"“([^”]+)” repeats “([^”]+)” in ({title})\."
    pairs = []
    assessment = message
    for match in re.finditer(pattern, message):
        new, existing, heading = match.groups()
        for index, section in enumerate(siblings):
            if (
                heading == section["title"]
                and existing in (section.get("content") or "")
                and new in (output.get("summary") or "")
            ):
                if not pairs:
                    assessment = message[: match.start()].strip()
                pairs.append(
                    {
                        "source_index": index,
                        "source_quote": existing,
                        "target_quote": new,
                    }
                )
                break
    return {"repetitions": pairs, "section_assessment": assessment}


def link_saved_repetitions(checks, output):
    return [
        (
            {**check, **_saved_pairs(check.get("message", ""), output)}
            if check.get("type") == "brief_overlap" and "repetitions" not in check
            else check
        )
        for check in checks
    ]
