"""
Generation router — study guides, flashcards, and quizzes via TerpAI.

Flow for each endpoint:
  1. Build a TerpAI prompt using context_builder templates
  2. Send to TerpAI, get response
  3. For JSON outputs (flashcards, quiz): parse response, fall back to Gemini if invalid
  4. Return structured response

POST /api/generate/study-guide
POST /api/generate/flashcards
POST /api/generate/quiz
"""

import json
from fastapi import APIRouter, HTTPException

from models.schemas import (
    GenerateRequest,
    StudyGuideResponse,
    FlashcardsResponse,
    FlashCard,
    QuizResponse,
    QuizQuestion,
)
from services.terpai import bridge, TerpAIError
from services.gemini import generate_json_fallback, generate_text_fallback
from prompts.context_builder import (
    build_terpai_study_guide_prompt,
    build_terpai_flashcards_prompt,
    build_terpai_quiz_prompt,
)
from prompts.study_guide import build_study_guide_prompt
from prompts.flashcards import build_flashcards_prompt
from prompts.quiz import build_quiz_prompt

try:
    from data.courses import COURSES
except ImportError:
    COURSES = []

router = APIRouter()


def _find_course(course_id: str) -> dict:
    for c in COURSES:
        if c["id"] == course_id:
            return c
    return {"id": course_id, "name": course_id.upper(), "topics": ["general topics"]}


def _sanitize_json_string(text: str) -> str:
    """Remove control characters that break JSON parsing (common in LLM output)."""
    import re
    # Replace literal newlines/tabs/carriage-returns with their escaped forms
    # This handles the most common LLM issue: newlines inside JSON string values
    text = text.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n').replace('\t', '\\t')
    # Remove any other control chars (0x00-0x1F) that aren't valid in JSON
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)
    return text


def _try_parse_json(text: str) -> dict | list | None:
    """Try to parse JSON from TerpAI response text (may have prose around it)."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Sanitize control characters and retry
    sanitized = _sanitize_json_string(text)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON block from prose
    import re
    # Find first { ... } or [ ... ] block
    for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
        matches = re.findall(pattern, sanitized)
        if matches:
            # Try the largest match (most likely the full JSON)
            for match in sorted(matches, key=len, reverse=True):
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    # Try with additional sanitization
                    try:
                        return json.loads(_sanitize_json_string(match))
                    except json.JSONDecodeError:
                        continue

    return None


async def _send_to_terpai_or_fallback_text(terpai_prompt: str, fallback_prompt: str, system: str) -> str:
    """Send to TerpAI, fall back to Gemini text if TerpAI fails."""
    if bridge._ready:
        try:
            return await bridge.send_prompt(terpai_prompt)
        except TerpAIError as e:
            pass  # fall through

    return await generate_text_fallback(fallback_prompt, system_instruction=system)


async def _send_to_terpai_or_fallback_json(terpai_prompt: str, fallback_prompt: str, system: str) -> dict | list:
    """Send to TerpAI, fall back to Gemini JSON if TerpAI returns non-JSON."""
    if bridge._ready:
        try:
            raw = await bridge.send_prompt(terpai_prompt)
            parsed = _try_parse_json(raw)
            if parsed is not None:
                return parsed
            # TerpAI returned prose — fall through to Gemini for JSON
        except TerpAIError:
            pass

    # Gemini as reliable JSON fallback
    return await generate_json_fallback(fallback_prompt, system_instruction=system)


# ─── Study Guide ──────────────────────────────────────────────────────────────

@router.post("/generate/study-guide", response_model=StudyGuideResponse)
async def generate_study_guide(request: GenerateRequest):
    """Generate a markdown study guide via TerpAI (Gemini fallback)."""
    course = _find_course(request.course_id)

    terpai_prompt = build_terpai_study_guide_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        additional_context=request.additional_context,
    )

    gemini_fallback_prompt = build_study_guide_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        course_topics=course.get("topics", []),
        additional_context=request.additional_context,
    )

    try:
        content = await _send_to_terpai_or_fallback_text(
            terpai_prompt=terpai_prompt,
            fallback_prompt=gemini_fallback_prompt,
            system="You are an expert academic tutor creating study materials.",
        )
        return StudyGuideResponse(
            content=content,
            topic=request.topic,
            course_id=request.course_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Study guide generation failed: {e}")


# ─── Flashcards ───────────────────────────────────────────────────────────────

@router.post("/generate/flashcards", response_model=FlashcardsResponse)
async def generate_flashcards(request: GenerateRequest):
    """Generate flashcards via TerpAI (Gemini JSON fallback if response isn't valid JSON)."""
    course = _find_course(request.course_id)

    terpai_prompt = build_terpai_flashcards_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        additional_context=request.additional_context,
    )

    gemini_fallback_prompt = build_flashcards_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        course_topics=course.get("topics", []),
        additional_context=request.additional_context,
    )

    try:
        result = await _send_to_terpai_or_fallback_json(
            terpai_prompt=terpai_prompt,
            fallback_prompt=gemini_fallback_prompt,
            system="You are an expert academic tutor. Generate flashcards as valid JSON only.",
        )

        cards_data = result.get("cards", result) if isinstance(result, dict) else result
        if not isinstance(cards_data, list):
            raise ValueError("Unexpected flashcard format")

        cards = [
            FlashCard(
                front=c["front"],
                back=c["back"],
                course_id=request.course_id,
            )
            for c in cards_data
        ]
        return FlashcardsResponse(cards=cards, topic=request.topic, course_id=request.course_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Flashcard generation failed: {e}")


# ─── Quiz ─────────────────────────────────────────────────────────────────────

@router.post("/generate/quiz", response_model=QuizResponse)
async def generate_quiz(request: GenerateRequest):
    """Generate quiz questions via TerpAI (Gemini JSON fallback if response isn't valid JSON)."""
    course = _find_course(request.course_id)

    terpai_prompt = build_terpai_quiz_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        additional_context=request.additional_context,
    )

    gemini_fallback_prompt = build_quiz_prompt(
        topic=request.topic,
        course_id=request.course_id,
        course_name=course["name"],
        course_topics=course.get("topics", []),
        additional_context=request.additional_context,
    )

    try:
        result = await _send_to_terpai_or_fallback_json(
            terpai_prompt=terpai_prompt,
            fallback_prompt=gemini_fallback_prompt,
            system="You are an expert academic tutor. Generate quiz questions as valid JSON only.",
        )

        questions_data = result.get("questions", result) if isinstance(result, dict) else result
        if not isinstance(questions_data, list):
            raise ValueError("Unexpected quiz format")

        questions = [
            QuizQuestion(
                question=q["question"],
                options=q["options"],
                correct_index=q["correct_index"],
                explanation=q["explanation"],
            )
            for q in questions_data
        ]
        return QuizResponse(questions=questions, topic=request.topic, course_id=request.course_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {e}")
