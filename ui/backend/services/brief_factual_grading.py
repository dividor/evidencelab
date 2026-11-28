"""Grade each numbered claim against the excerpts cited in that claim."""

from pydantic import BaseModel, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_experiment_claims import brief_claim_evidence
from ui.backend.services.citation_fidelity import locate_quote, quotable_text


class SupportingQuote(BaseModel):
    citation: int = Field(ge=1)
    quote: str = Field(min_length=1, pattern=r"\S")


class ClaimGrade(BaseModel):
    claim: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, pattern=r"\S")
    factual: bool = Field(strict=True)
    unmet: list[str]
    supporting_quotes: list[SupportingQuote] = Field(default_factory=list)
    score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_score(self):
        if not self.factual and (
            self.score != 1 or self.unmet or self.supporting_quotes
        ):
            raise ValueError(
                "A nonfactual transition must have full credit and no evidence findings."
            )
        if 0 < self.score < 1 and not any(gap.strip() for gap in self.unmet):
            raise ValueError(
                "Partial credit requires a specific unsupported part of the claim."
            )
        if self.unmet and self.score == 1:
            raise ValueError(
                "A claim with an unsupported element cannot receive full credit."
            )
        return self


class ClaimGrades(BaseModel):
    claims: list[dict]


def _evidence_issue(grade, claim, sources):
    if grade.factual and grade.score > 0 and not grade.supporting_quotes:
        return "The judge gave credit without a supporting quote."
    for quote in grade.supporting_quotes:
        label = str(quote.citation)
        if label not in claim["citations"] or label not in sources:
            return f"The judge quoted [{label}], which this claim does not cite."
        if (
            locate_quote(quote.quote, [quotable_text(sources[label])])["status"]
            == "missing"
        ):
            return f"The judge’s quote could not be found in [{label}]: {quote.quote}"
    return ""


def _claim_inputs(output):
    evidence = brief_claim_evidence(output)
    claims = []
    sources = {}
    for paragraph in evidence["paragraphs"]:
        for claim in paragraph:
            labels = []
            for index in claim["references"]:
                ref = evidence["references"][index]
                label = ref["label"]
                labels.append(label)
                if ref["source_position"] is not None:
                    source = output["sources"][ref["source_position"]]
                    sources[label] = {
                        key: source[key]
                        for key in ("title", "page", "headings", "text")
                        if key in source
                    }
            claims.append(
                dict(
                    claim=len(claims) + 1,
                    text="".join(p["text"] for p in claim["parts"]),
                    citations=labels,
                )
            )
    return claims, sources


def _read_claim(rows, claim, sources):
    number = claim["claim"]
    matched = [r for r in rows if r.get("claim") == number]
    if len(matched) != 1:
        return None, "The judge must return one grade for this claim."
    try:
        grade = ClaimGrade.model_validate(matched[0])
    except ValidationError as exc:
        problem = exc.errors(include_input=False, include_url=False)[0]
        if problem["type"] == "value_error":
            return None, str(problem["ctx"]["error"])
        if problem["loc"][:1] == ("supporting_quotes",):
            return (
                None,
                "Each supporting quote must contain a citation number and a nonempty quote.",
            )
        return None, "The judge returned an incomplete or inconsistent grade."
    cited = any(
        (sources.get(label, {}).get("text") or "").strip()
        for label in claim["citations"]
    )
    if grade.factual and claim["citations"] and not cited:
        return (
            dict(
                claim=number,
                error=True,
                outcome="missing_source",
                reason="The cited excerpt is missing or empty.",
            ),
            "",
        )
    if grade.factual and not cited and grade.score > 0:
        return grade.model_dump(), "An uncited factual claim cannot receive credit."
    issue = _evidence_issue(grade, claim, sources)
    return {**grade.model_dump(), "outcome": _outcome(grade, cited)}, issue


def _outcome(grade, cited):
    if not grade.factual:
        return "nonfactual"
    return "assessed" if cited else "uncited"


def _read_batch(raw, pending, sources):
    try:
        rows = ClaimGrades.model_validate_json(raw).claims
    except ValidationError:
        rows = []
    return [(c["claim"], *_read_claim(rows, c, sources)) for c in pending]


def _unresolved_grade(number, grade, issue):
    if grade is None:
        return dict(claim=number, error=True, outcome="grading_error", reason=issue)
    return {
        **grade,
        "outcome": "unverified_evidence",
        "evidence_failed": True,
        "score": 0.0,
        "reason": issue,
        "unmet": [*grade["unmet"], issue],
    }


def _quote_locations(claim, sources, previous):
    """Locate the prior reply's quotes only in the references on this sentence."""
    excerpts = {
        label: quotable_text(sources[label])
        for label in claim["citations"]
        if label in sources
    }
    locations = []
    for quote in previous.get("supporting_quotes", []):
        matches = {}
        for label, excerpt in excerpts.items():
            status = locate_quote(quote["quote"], [excerpt])["status"]
            if status != "missing":
                matches[label] = status
        locations.append({**quote, "found_in": matches})
    return locations


def _repair_prompt(template, pending, sources, issues, ungraded):
    return template.render(
        repair=[c["claim"] for c in pending],
        problems=issues,
        quote_locations={
            c["claim"]: _quote_locations(c, sources, ungraded[c["claim"]])
            for c in pending
        },
        uncited=[
            c["claim"]
            for c in pending
            if not any(sources.get(k, {}).get("text") for k in c["citations"])
        ],
    )


async def _grade_batch(claims, sources, context, template, output, model):
    from ui.backend.services.test_runner import _judge_call

    accepted, issues, prompts = {}, {}, []
    ungraded = {}
    for _ in range(2):
        pending = [c for c in claims if c["claim"] not in accepted]
        labels = {label for c in pending for label in c["citations"]}
        system = template.render(system=True, example_claim=pending[0]["claim"])
        prompt = template.render(
            **context,
            claims=pending,
            sources={k: v for k, v in sources.items() if k in labels},
        )
        if issues:
            prompt += "\n" + await run_in_threadpool(
                _repair_prompt, template, pending, sources, issues, ungraded
            )
        prompts.append(system + "\n\n" + prompt)
        raw, usage = await _judge_call(prompt, model, system, max_tokens=2400)
        output.setdefault("judge_usage", []).append(usage)
        for number, grade, issue in await run_in_threadpool(
            _read_batch, raw, pending, sources
        ):
            if issue:
                issues[number] = issue
                if grade is not None or number not in ungraded:
                    ungraded[number] = _unresolved_grade(number, grade, issue)
            else:
                accepted[number] = grade
                issues.pop(number, None)
        if not issues:
            break
    return [
        accepted.get(c["claim"]) or ungraded[c["claim"]] for c in claims
    ], "\n\n".join(prompts)


async def grade_factual_claims(output, rubric, model):
    claims, sources = _claim_inputs(output)
    template = assistant_prompt_templates.get_template("brief_factual_grading.j2")
    grades, prompts = [], []
    for start in range(0, len(claims), 8):
        batch = claims[start : start + 8]
        context = dict(
            rubric=rubric,
            draft=output["summary"],
            guidance={
                k: v
                for k, v in output.get("reference_standard", {}).items()
                if k != "source"
            },
        )
        results, sent = await _grade_batch(
            batch, sources, context, template, output, model
        )
        grades.extend(results)
        prompts.append(sent)
    return grades, "\n\n".join(prompts)
