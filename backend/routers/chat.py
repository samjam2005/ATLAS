"""
Chat router — Aether Agent Layer pipeline.

Flow:
  1. Build TerpAI prompt (context history + user question)
  2. Send to TerpAI via Playwright automation
  3. Return response as SSE stream
  4. If TerpAI fails → fall back to Gemini directly

POST /api/chat
"""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models.schemas import ChatRequest
from services.terpai import bridge, TerpAIError
from services.gemini import generate_text_fallback
from prompts.context_builder import build_terpai_chat_prompt
from prompts.chat_system import build_chat_system_prompt

# Import mock data (populated by Person 3)
try:
    from data.courses import COURSES
    from data.assignments import ASSIGNMENTS
    from data.notes import NOTES
except ImportError:
    COURSES = []
    ASSIGNMENTS = []
    NOTES = []

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Main chat endpoint.

    Primary path: Gemini context → TerpAI response → SSE stream
    Fallback path: Gemini answers directly if TerpAI is unavailable
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    # The latest user message
    last_message = request.messages[-1].content
    history = [
        {"role": m.role, "content": m.content}
        for m in request.messages[:-1]  # all except last
    ]

    # Map raw assignment IDs to their human-readable names so TerpAI knows what 'a2' is
    named_triage = {}
    if request.triage_statuses:
        for aid, stat in request.triage_statuses.items():
            assignment = next((a for a in ASSIGNMENTS if a.get("id") == aid), None)
            name = assignment.get("name", aid) if assignment else aid
            named_triage[name] = stat

    # Build the full prompt for TerpAI
    terpai_prompt = build_terpai_chat_prompt(
        user_question=last_message,
        conversation_history=history if history else None,
        triage_statuses=named_triage,
        system_status=request.system_status,
        active_remediation=request.active_remediation,
        upcoming_deadlines=request.upcoming_deadlines,
        graph_context=request.graph_context,
        graph_connections=request.graph_connections,
    )

    async def event_stream():
        response_text = None

        # ── Primary: TerpAI ──────────────────────────────────────────────────
        if bridge._ready:
            try:
                if request.agent_url:
                    response_text = await bridge.send_prompt_to_agent(request.agent_url, terpai_prompt)
                else:
                    response_text = await bridge.send_prompt(terpai_prompt)
            except TerpAIError as e:
                import logging
                logging.getLogger("chat").warning(f"TerpAI failed, falling back to Gemini: {e}")
                # Log and fall through to Gemini fallback
                error_note = json.dumps({"status": "terpai_fallback", "note": str(e)})
                yield f"data: {error_note}\n\n"

        # ── Fallback: Gemini direct ──────────────────────────────────────────
        if response_text is None:
            import logging
            logging.getLogger("chat").info("Starting Gemini fallback generation...")
            try:
                # Optional: The chat fallback could also include remediation context if desired,
                # but we'll focus mostly on the courses logic.
                system_prompt = build_chat_system_prompt(
                    courses=COURSES,
                    assignments=ASSIGNMENTS,
                    notes=NOTES,
                    course_filter=request.course_context,
                    triage_statuses=request.triage_statuses,
                    active_remediation=request.active_remediation,
                )
                full_prompt = f"{system_prompt}\n\nStudent: {last_message}"
                response_text = await generate_text_fallback(
                    full_prompt,
                    system_instruction="You are Aether, an NTU Singapore study assistant.",
                )
                logging.getLogger("chat").info(f"Gemini generation complete ({len(response_text)} chars)")
            except Exception as e:
                logging.getLogger("chat").error(f"Gemini fallback failed: {e}")
                err = json.dumps({"error": f"Both TerpAI and Gemini failed: {str(e)}"})
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return

        # Stream the response in chunks for a natural feel
        # TerpAI isn't streaming, so we simulate by chunking the response
        chunk_size = 50  # characters per chunk
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i : i + chunk_size]
            data = json.dumps({"content": chunk})
            yield f"data: {data}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
