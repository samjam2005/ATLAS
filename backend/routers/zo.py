"""
ZO email agent router.

POST /api/zo/parse   — accepts raw email text, returns structured digest
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.zo_client import parse_emails

log = logging.getLogger(__name__)
router = APIRouter()


class ZOParseRequest(BaseModel):
    email_text: str


class ZODigest(BaseModel):
    summary: str
    upcoming_events: list = []
    exams: list = []
    meetings: list = []
    deadlines: list = []
    action_items: list = []
    needs_reply: list = []


@router.post("/zo/parse", response_model=ZODigest)
async def zo_parse(request: ZOParseRequest):
    """
    Send raw email text to ZO and return a structured academic digest.
    The frontend is responsible for fetching email content from Outlook
    and passing the combined text here.
    """
    if not request.email_text.strip():
        raise HTTPException(status_code=400, detail="email_text cannot be empty")

    try:
        result = await parse_emails(request.email_text)
        return ZODigest(
            summary=result.get("summary", ""),
            upcoming_events=result.get("upcoming_events", []),
            exams=result.get("exams", []),
            meetings=result.get("meetings", []),
            deadlines=result.get("deadlines", []),
            action_items=result.get("action_items", []),
            needs_reply=result.get("needs_reply", []),
        )
    except Exception as e:
        log.error(f"ZO parse failed: {e}")
        raise HTTPException(status_code=502, detail=f"ZO API error: {str(e)}")
