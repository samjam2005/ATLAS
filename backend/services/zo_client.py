"""
ZO email agent client.
Calls Armaan's hosted ZO endpoint which digests emails + calendar items
into a structured daily-digest response.
"""

import os
import logging
import httpx

log = logging.getLogger(__name__)

ZO_API_URL = "https://armaanking.zo.space/api/email-summary"


async def parse_emails(email_text: str) -> dict:
    """
    Send email content to the ZO daily-digest endpoint and return
    the structured result dict (summary, deadlines, exams, etc.).

    email_text is split into a single email item so the API receives
    a well-formed `emails` array. Raises httpx.HTTPStatusError on
    non-2xx responses.
    """
    shared_secret = os.getenv("EMAIL_SUMMARY_SHARED_SECRET", "")

    payload = {
        "timezone": "Asia/Singapore",
        "mode": "daily-digest",
        "max_items": 25,
        "emails": [{"body": email_text}] if email_text.strip() else [],
        "calendar_items": [],
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {shared_secret}",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(ZO_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        # The endpoint returns { result: { ... } } — unwrap it
        return data.get("result", data)
