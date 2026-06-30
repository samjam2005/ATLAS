"""
Career router — the 'Sup career layer on top of Aether's academic data.

Three capabilities, each grounded in the student's REAL coursework:

  POST /api/career/profile    Auto-build an evidence-backed career profile +
                              resume bullets from the mastery graph and the
                              projects the student actually completed.
                              (Aether Copilot primary, Gemini JSON fallback.)

  POST /api/career/match      Score curated jobs/internships against the
                              student's mastery-weighted profile. Deterministic
                              (no LLM) so it's instant and demo-reliable, and
                              returns the skill gaps that feed Aether's
                              remediation loop.

  POST /api/career/interview  Mock interview questions drilled on the student's
                              real projects, for a target role.
                              (Aether Copilot primary, Gemini JSON fallback.)
"""

import json
import re
from collections import defaultdict

from fastapi import APIRouter, HTTPException

from models.career_schemas import (
    CareerProfileRequest,
    CareerProfileResponse,
    ProfileStrength,
    JobMatchRequest,
    JobMatchResponse,
    JobMatch,
    SkillMatch,
    InterviewPrepRequest,
    InterviewPrepResponse,
    InterviewQuestion,
)
from services.terpai import bridge, TerpAIError
from services.gemini import generate_json_fallback
from prompts.career import build_profile_prompt, build_interview_prompt

try:
    from data.jobs import JOBS
except ImportError:
    JOBS = []

router = APIRouter()


# ─── JSON parsing (mirror of generate.py, kept local so this stays drop-in) ──

def _sanitize_json_string(text: str) -> str:
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n").replace("\t", "\\t")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


def _try_parse_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    sanitized = _sanitize_json_string(text)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass
    for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
        for match in sorted(re.findall(pattern, sanitized), key=len, reverse=True):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                try:
                    return json.loads(_sanitize_json_string(match))
                except json.JSONDecodeError:
                    continue
    return None


async def _terpai_or_gemini_json(prompt: str, system: str):
    """Aether Copilot primary, Gemini JSON fallback. Same prompt to both paths."""
    if bridge._ready:
        try:
            raw = await bridge.send_prompt(prompt)
            parsed = _try_parse_json(raw)
            if parsed is not None:
                return parsed
        except TerpAIError:
            pass
    return await generate_json_fallback(prompt, system_instruction=system)


# ─── Shared context builders ─────────────────────────────────────────────────

def _profile_summary(concepts, projects) -> str:
    by_course: dict[str, list] = defaultdict(list)
    for c in concepts:
        by_course[(c.course_id or "general").upper()].append(c)

    lines: list[str] = []
    for course, items in sorted(by_course.items()):
        items.sort(key=lambda c: c.mastery, reverse=True)
        lines.append(f"### {course}")
        for c in items:
            lines.append(f"- {c.label}: {c.mastery}% mastery")
        lines.append("")
    return "\n".join(lines).strip() or "(no concept data provided)"


def _projects_block(projects) -> str:
    if not projects:
        return "(no completed projects provided)"
    return "\n".join(
        f"- {p.name}"
        + (f" [{p.course_id.upper()}]" if p.course_id else "")
        + (f": {p.description}" if p.description else "")
        for p in projects
    )


# ─── Fuzzy skill ↔ concept matching (for deterministic job scoring) ──────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _best_match(skill: str, concept_map: dict[str, tuple[str, int]]):
    """Return (orig_label, mastery, score) for the best concept matching `skill`,
    or None if nothing clears the 0.5 threshold."""
    skill_n = _norm(skill)
    skill_tokens = set(skill_n.split())
    best = None
    best_score = 0.0
    for label_n, (orig, mastery) in concept_map.items():
        if skill_n == label_n:
            return (orig, mastery, 1.0)
        if skill_n in label_n or label_n in skill_n:
            score = 0.85
        else:
            label_tokens = set(label_n.split())
            union = skill_tokens | label_tokens
            score = (len(skill_tokens & label_tokens) / len(union)) if union else 0.0
        if score > best_score:
            best_score = score
            best = (orig, mastery)
    if best and best_score >= 0.5:
        return (best[0], best[1], best_score)
    return None


def _score_job(job: dict, concept_map: dict[str, tuple[str, int]]) -> JobMatch:
    matched: list[SkillMatch] = []
    missing: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for skills, weight in ((job.get("required_skills", []), 1.0),
                           (job.get("preferred_skills", []), 0.5)):
        for skill in skills:
            weight_total += weight
            m = _best_match(skill, concept_map)
            coverage = (m[1] / 100.0) if m else 0.0
            weighted_sum += weight * coverage
            if m and m[1] >= 50:
                matched.append(SkillMatch(skill=skill, mastery=m[1], matched_concept=m[0]))
            elif weight == 1.0:
                # only required skills become actionable gaps for remediation
                missing.append(skill)

    fit = round(100 * weighted_sum / weight_total) if weight_total else 0
    matched.sort(key=lambda s: s.mastery, reverse=True)

    return JobMatch(
        id=job["id"],
        title=job["title"],
        company=job["company"],
        location=job["location"],
        type=job["type"],
        level=job["level"],
        salary=job["salary"],
        source=job["source"],
        url=job["url"],
        summary=job["summary"],
        tags=job.get("tags", []),
        fit_score=fit,
        matched_skills=matched[:6],
        missing_skills=missing[:5],
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/career/profile", response_model=CareerProfileResponse)
async def career_profile(request: CareerProfileRequest):
    """Build an evidence-backed career profile from the mastery graph."""
    prompt = build_profile_prompt(
        profile_summary=_profile_summary(request.concepts, request.projects)
        + "\n\n## Completed Projects\n"
        + _projects_block(request.projects),
        target=request.target,
    )
    try:
        result = await _terpai_or_gemini_json(
            prompt, system="You output valid JSON career profiles only."
        )
        if not isinstance(result, dict):
            raise ValueError("Unexpected profile format")
        strengths = [
            ProfileStrength(
                skill=s.get("skill", ""),
                mastery=int(s.get("mastery", 0) or 0),
                evidence=s.get("evidence", ""),
            )
            for s in result.get("strengths", [])
            if isinstance(s, dict)
        ]
        return CareerProfileResponse(
            headline=result.get("headline", ""),
            summary=result.get("summary", ""),
            strengths=strengths,
            developing=result.get("developing", []),
            resume_bullets=result.get("resume_bullets", []),
            suggested_roles=result.get("suggested_roles", []),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile generation failed: {e}")


@router.post("/career/match", response_model=JobMatchResponse)
async def career_match(request: JobMatchRequest):
    """Score curated jobs against the student's mastery profile. Deterministic."""
    concept_map: dict[str, tuple[str, int]] = {}
    for c in request.concepts:
        key = _norm(c.label)
        # keep the highest mastery if a label appears twice
        if key not in concept_map or c.mastery > concept_map[key][1]:
            concept_map[key] = (c.label, c.mastery)

    matches = [_score_job(job, concept_map) for job in JOBS]
    matches.sort(key=lambda m: m.fit_score, reverse=True)
    return JobMatchResponse(matches=matches[: request.limit])


@router.post("/career/interview", response_model=InterviewPrepResponse)
async def career_interview(request: InterviewPrepRequest):
    """Generate mock interview questions grounded in the student's real projects."""
    if not request.role.strip():
        raise HTTPException(status_code=400, detail="role is required")

    prompt = build_interview_prompt(
        role=request.role,
        profile_summary=_profile_summary(request.concepts, request.projects),
        projects=_projects_block(request.projects),
        count=request.count,
    )
    try:
        result = await _terpai_or_gemini_json(
            prompt, system="You output valid JSON interview questions only."
        )
        questions_data = result.get("questions", result) if isinstance(result, dict) else result
        if not isinstance(questions_data, list):
            raise ValueError("Unexpected interview format")
        questions = [
            InterviewQuestion(
                type=q.get("type", "technical"),
                question=q.get("question", ""),
                grounded_in=q.get("grounded_in", ""),
                assesses=q.get("assesses", ""),
                answer_hint=q.get("answer_hint", ""),
            )
            for q in questions_data
            if isinstance(q, dict) and q.get("question")
        ]
        return InterviewPrepResponse(role=request.role, questions=questions)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Interview prep failed: {e}")
