"""Apply the experiment expectations to a saved version, without generating text."""

from itertools import takewhile
from uuid import UUID

from sqlalchemy import select

from ui.backend.auth.models import VoiceProfile
from ui.backend.services.brief_claim_records import SOURCE_FIELDS
from ui.backend.services.brief_experiment import judge_brief
from ui.backend.services.brief_experiment_claims import (
    brief_claim_evidence,
    link_assessment_claims,
)
from ui.backend.services.brief_grading_errors import brief_grading_error
from ui.backend.services.brief_outline_numbers import outline_numbers
from ui.backend.services.brief_template_evaluation import (
    DEFAULT_BRIEF_EXPECTATIONS,
    grade_template_checks,
    introduction_word_target,
    section_word_target,
)
from ui.backend.services.citation_fidelity import (
    researched_sections,
    strip_citation_markers,
)


async def version_profiles(session, content, version_time):
    ids = {s.get("voiceId") for s in content.get("sections", [])}
    ids.add(content.get("voiceId"))
    ids.discard(None)
    if not ids:
        return {}
    rows = await session.scalars(
        select(VoiceProfile).where(VoiceProfile.id.in_([UUID(i) for i in ids]))
    )
    # Profiles are editable. A later edit cannot establish the instructions
    # that applied when this version was saved.
    return {
        str(p.id): dict(id=str(p.id), name=p.name, instructions=p.instructions)
        for p in rows
        if p.updated_at <= version_time
    }


def section_inputs(content, profiles):
    visible = {s["id"]: s for s in researched_sections(content)}
    sections = content.get("sections", [])
    outline = [
        dict(
            title=s["title"],
            level=s.get("level", 1),
            content=visible.get(s["id"], {}).get("content", ""),
        )
        for s in sections
    ]
    numbers = outline_numbers(s["level"] == 2 for s in outline)
    intro_target = introduction_word_target()
    for i, section in enumerate(sections):
        children = (
            list(takewhile(lambda s: s["level"] == 2, outline[i + 1 :]))
            if outline[i]["level"] == 1
            else []
        )
        text = outline[i]["content"]
        voice_id = section.get("voiceId") or content.get("voiceId")
        profile = profiles.get(voice_id)
        assignment = dict(
            topic=content.get("query") or content.get("title", ""),
            heading=section["title"],
            heading_number=numbers[i],
            child_headings=[s["title"] for s in children],
            instructions=content.get("instructions"),
            guidance=section.get("guidance") or "",
            target_words=section_word_target(
                section.get("targetWords"),
                content.get("targetWords"),
                children,
                intro_target,
            ),
            voice_profile=profile,
            voice=profile["instructions"] if profile else None,
        )
        yield dict(
            capability="brief",
            summary=text,
            written=bool(text.strip()),
            sources=visible.get(section["id"], {}).get("sources", []),
            siblings=outline[:i] + outline[i + 1 :],
            assignment=assignment,
            words=len(strip_citation_markers(text).split()),
            reference_standard={},
        ), section["id"], bool(voice_id and not profile)


def _checks_for(output, position, missing_voice):
    reasons = {}
    if not output["assignment"]["child_headings"]:
        reasons["brief_intro_scope"] = "This section has no subheadings to introduce."
    if not output["assignment"]["target_words"]:
        reasons["brief_length"] = "This section has no word target."
    if not any(s["content"] for s in output["siblings"][:position]):
        reasons["brief_overlap"] = (
            "No earlier written section to compare. Later sections are checked against this one."
        )
    if missing_voice:
        reasons["brief_voice"] = (
            "The selected voice profile's instructions for this version are unavailable."
        )
    return reasons


async def grade_saved_section(output, position, missing_voice, model):
    reasons = _checks_for(output, position, missing_voice)

    async def judge(draft, checks):
        if checks[0]["type"] == "brief_overlap":
            # Compare each pair once. Earlier siblings occupy the same
            # positions in the full saved outline used for displaying quotes.
            draft = {
                **draft,
                "siblings": draft["siblings"][:position],
                "judge_usage": draft.setdefault("judge_usage", []),
            }
        return await judge_brief(draft, checks, model)

    checks = DEFAULT_BRIEF_EXPECTATIONS
    if not output["written"]:
        return [
            dict(**a, not_run=True, message="No section text was saved.")
            for a in checks
        ]
    graded = iter(
        await grade_template_checks(
            output, [a for a in checks if a["type"] not in reasons], judge
        )
    )
    ordered = [
        (
            dict(
                **a,
                applicable=False,
                not_run=(a["type"] == "brief_voice"),
                message=reasons[a["type"]]
            )
            if a["type"] in reasons
            else next(graded)
        )
        for a in checks
    ]
    return ordered


def section_result(output, checks, section_id, missing_voice):
    status = "pass"
    if any(c.get("passed") is False for c in checks):
        status = "fail"
    if not output["written"] or missing_voice or any(c.get("error") for c in checks):
        status = "error"
    evidence = brief_claim_evidence(output)
    snapshot = {k: v for k, v in output.items() if k != "judge_usage"}
    # The evaluation view reads the numbered excerpts. Viewer coordinates
    # and generation-time highlights belong to the original document.
    snapshot["sources"] = [
        {key: src[key] for key in SOURCE_FIELDS if key in src}
        for src in output["sources"]
    ]
    return dict(
        section_id=section_id,
        heading=output["assignment"]["heading"],
        number=output["assignment"]["heading_number"],
        status=status,
        brief_evidence=evidence,
        actual_output=snapshot,
        assertion_results=(
            link_assessment_claims(checks, evidence) if evidence else checks
        ),
    )


def section_metrics(section):
    """Use the experiment's lowest graded score, excluding inapplicable checks."""
    checks = section["assertion_results"]
    if section["status"] == "error":
        error = brief_grading_error(checks) or next(
            (c["message"] for c in checks if c.get("not_run")), None
        )
        return dict(score=None, error_message=error)
    return dict(
        score=min(
            (c["score"] for c in checks if c.get("score") is not None), default=None
        ),
        error_message=None,
    )
