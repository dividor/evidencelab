"""Grade each numbered claim against the excerpts cited in that claim."""

from pydantic import BaseModel, Field, ValidationError, model_validator

from ui.backend.services.assistant_settings import assistant_prompt_templates
from ui.backend.services.brief_experiment_claims import brief_claim_evidence


class ClaimGrade(BaseModel):
    claim: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, pattern=r"\S")
    factual: bool = Field(strict=True, exclude=True)
    unmet: list[str] = Field(exclude=True)
    score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_score(self):
        if self.unmet and self.score == 1:
            raise ValueError(
                "A claim with an unsupported element cannot receive full credit."
            )
        return self


class ClaimGrades(BaseModel):
    claims: list[ClaimGrade]


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


async def _grade_batch(claims, sources, prompt, system, output, model):
    from ui.backend.services.test_runner import _judge_call

    expected = [item["claim"] for item in claims]
    uncited = {
        item["claim"]
        for item in claims
        if not any(sources.get(label, {}).get("text") for label in item["citations"])
    }
    for attempt in range(2):
        raw, usage = await _judge_call(prompt, model, system, max_tokens=1600)
        output.setdefault("judge_usage", []).append(usage)
        try:
            grades = sorted(
                ClaimGrades.model_validate_json(raw).claims, key=lambda g: g.claim
            )
            unsupported = any(
                g.factual and g.claim in uncited and g.score > 0 for g in grades
            )
            if [grade.claim for grade in grades] == expected and not unsupported:
                return [
                    grade.model_dump() for grade in grades
                ], system + "\n\n" + prompt
        except ValidationError:
            pass
        if not attempt:
            template = assistant_prompt_templates.get_template(
                "brief_factual_grading.j2"
            )
            prompt += "\n" + template.render(repair=expected, uncited=sorted(uncited))
    raise ValueError(
        "The factual support judge did not return one valid grade per claim."
    )


async def grade_factual_claims(output, rubric, model):
    claims, sources = _claim_inputs(output)
    template = assistant_prompt_templates.get_template("brief_factual_grading.j2")
    system = template.render(system=True)
    grades, prompts = [], []
    for start in range(0, len(claims), 8):
        batch = claims[start : start + 8]
        labels = dict.fromkeys(label for item in batch for label in item["citations"])
        prompt = template.render(
            rubric=rubric,
            claims=batch,
            draft=output["summary"],
            guidance={
                k: v
                for k, v in output.get("reference_standard", {}).items()
                if k != "source"
            },
            sources={label: sources[label] for label in labels if label in sources},
        )
        results, sent = await _grade_batch(
            batch, sources, prompt, system, output, model
        )
        grades.extend(results)
        prompts.append(sent)
    return grades, "\n\n".join(prompts)
