"""
TerpAI API Bridge
=================
Direct HTTP API client for TerpAI (https://terpai.umd.edu).
Replaces the old Playwright browser automation with clean httpx calls.

Auth: Bearer JWT token from .env (TERPAI_TOKEN).
      Grab from Chrome DevTools: F12 → Network → any TerpAI request →
      copy Authorization header value. Valid ~30 min.

API Surface (NebulOne platform):
  - POST /api/conversations                              → send message (SSE stream)
  - POST /api/internal/attachments                        → upload knowledge file
  - PUT  /api/internal/configStates/{id}                  → save agent config
  - POST /api/internal/configStates/{id}/createGptSystem  → finalize new agent
  - PUT  /api/internal/configStates/{id}/updateGptSystem  → finalize agent update
  - GET  /api/internal/configStates/{id}                  → read agent config
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid

import httpx

log = logging.getLogger("terpai")

# ─── Configuration ────────────────────────────────────────────────────────────

TERPAI_BASE_URL = "https://terpai.umd.edu"
TERPAI_API_URL = f"{TERPAI_BASE_URL}/api"

# Base system prompt injected into every TerpAI agent we create
AETHER_SYSTEM_PROMPT = """\
You are Aether, an AI study assistant for Nanyang Technological University (NTU Singapore) students.
You have been given detailed knowledge about the student's current modules, assignments, deadlines, and notes through your knowledge base documents.

Your role:
- Help students understand module material (e.g. SC2002, SC2001, MH1812, SC2005)
- Use NTU conventions: modules (not courses), AUs, tutorials, labs, lectures, and a CGPA on a 5.00 scale
- Answer questions using the knowledge base context provided to you
- Be encouraging, precise, and specific to their actual coursework
- Note that academic data shown is mock/demo data unless a real NTULearn/LMS connector is enabled

Output formatting rules (IMPORTANT - follow exactly):
- For normal chat: respond in clear markdown (headers, lists, code blocks as needed)
- When asked for FLASHCARDS: respond ONLY with a JSON object: {"cards": [{"front": "...", "back": "...", "course_id": "..."}]}
- When asked for a QUIZ: respond ONLY with a JSON object: {"questions": [{"question": "...", "options": ["A","B","C","D"], "correct_index": 0, "explanation": "..."}]}
- When asked for CONCEPTS: respond ONLY with a JSON object: {"nodes": [{"id": "...", "label": "...", "course_id": "...", "description": "..."}], "edges": [{"source": "...", "target": "...", "relationship": "..."}]}
- When asked for a STUDY GUIDE: respond with well-structured markdown

Always ground your answers in the student's actual course context from the knowledge base.

Today's date is {{today}}."""

# Default NebulOne system prompt (the platform's own formatting instructions)
_NEBULONE_DEFAULT_SYSTEM_PROMPT = """\
You are an AI assistant designed to provide accurate, comprehensive, and useful responses. Your primary goal is to deliver value through assistance.

## Formatting:
    - Use Markdown: Format all responses in markdown for enhanced readability.
    - Headers & Emphasis: Use bold text for key points and increase font size for headers and sub headers.
    - Tailor responses to user preferences using structured formats like paragraphs or lists.
    - Equations: Use LaTeX notation to render equations, expressions and symbols (KaTeX spec)
    - Equation delimiters: Always delimit ALL mathematical notation by wrapping with double dollar signs ($$) to ensure correct display. This applies even when listing variables or briefly referencing equation parts.
        - Inline expressions: wrap with double dollar signs ($$...$$).
        - Block equations: place double dollar signs on separate lines.
        - When explaining components of an equation in bullet lists, each mathematical element must be wrapped in dollar signs (not just bolded). 
        - Ensure that ALL mathematical content follows these formatting rules for consistency and clarity, with no exceptions.
\t  
## Technical Queries:
    - Specify Context: Clearly indicate the programming language or context involved.
    - Use Code Blocks: Provide coding responses in markdown code blocks with practical insights.
\t
## User Engagement:
    - Empathy & Professionalism: Address sensitive topics with empathy and professionalism.
    - Step-by-Step Instructions: Offer detailed, step-by-step guidance where applicable.
\t
## Ethical Standards:
    - Critical Thinking: Encourage users to verify information and provide relevant resources.
\t
## Feedback & Improvement:
    - Clarifying Questions: If users express dissatisfaction, ask clarifying questions to refine responses.
\t
Today's date is {{today}}."""


# ─── Exceptions ───────────────────────────────────────────────────────────────

class TerpAIError(Exception):
    """Raised when TerpAI API call fails. Callers should fall back to Gemini."""
    pass


class TerpAILoginRequired(TerpAIError):
    """Token expired or missing."""
    pass


# ─── Main Bridge Class ─────────────────────────────────────────────────────────

class TerpAIBridge:
    """
    HTTP API bridge for TerpAI (NebulOne platform).
    Lifecycle managed by FastAPI lifespan (start/stop).
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._lock = asyncio.Lock()
        self._agent_chat_url: str | None = None
        self._agent_config_state_id: str | None = None
        self._agent_id: str | None = None
        self._conversation_id: str | None = None
        self._last_segment_id: str | None = None
        self._ready = False
        self._last_context_hash: str | None = None
        # Cache of specialized agent URL → context document (knowledge doc)
        self._agent_contexts: dict[str, str] = {}

    # ─── Auth Headers ─────────────────────────────────────────────────────

    def _headers(self, content_type: str = "application/json") -> dict:
        """Build request headers with Bearer token."""
        if not self._token:
            raise TerpAILoginRequired("TERPAI_TOKEN not set in .env")
        h = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "*/*",
            "Origin": TERPAI_BASE_URL,
            "Referer": f"{TERPAI_BASE_URL}/",
            "x-timezone": "America/New_York",
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self):
        """Initialize HTTP client and load token. Called at app startup."""
        log.info("Starting TerpAI API bridge...")

        self._token = os.getenv("TERPAI_TOKEN", "").strip()
        self._agent_chat_url = os.getenv("TERPAI_AGENT_URL", "").strip() or None

        if not self._token:
            log.warning(
                "TERPAI_TOKEN not set in .env. "
                "TerpAI unavailable -- falling back to Gemini. "
                "To get a token: F12 > Network > send a TerpAI message > "
                "copy the Authorization: Bearer ... value."
            )
            self._ready = False
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=10.0),
            follow_redirects=True,
            verify=False,  # TerpAI's cert chain fails on some Windows machines
        )

        # Quick auth check. A 401 here means the token is invalid/expired, so we
        # honestly report the agent layer as NOT ready and fall back to Gemini —
        # rather than claiming readiness and failing on the first real request.
        try:
            resp = await self._client.get(
                f"{TERPAI_API_URL}/internal/CurrentUser/pinnedGptSystems",
                headers=self._headers(),
            )
            if resp.status_code == 401:
                log.warning(
                    "TERPAI_TOKEN is invalid or expired (401 on auth check). "
                    "Agent layer disabled — using Gemini fallback. "
                    "Paste a fresh token in backend/.env (TERPAI_TOKEN) to enable it."
                )
                self._ready = False
                return
            log.info("Agent layer token accepted.")
        except Exception as e:
            # Network/transient errors shouldn't permanently disable the layer.
            log.warning(f"Could not verify agent-layer token: {e}. Proceeding anyway.")

        self._ready = True
        if self._agent_chat_url:
            log.info(f"Agent chat URL: {self._agent_chat_url}")

    async def stop(self):
        """Close HTTP client. Called at app shutdown."""
        log.info("Shutting down TerpAI API bridge...")
        if self._client:
            await self._client.aclose()
            self._client = None
        self._ready = False

    # ─── Agent Setup ──────────────────────────────────────────────────────

    async def setup_or_find_agent(self) -> str:
        """
        Find the Aether agent or use the hardcoded URL from .env.
        Returns the agent's chat page URL.
        """
        if not self._ready:
            raise TerpAIError("TerpAI bridge not ready (token missing?)")

        # Use direct URL from .env
        direct_url = os.getenv("TERPAI_AGENT_URL", "").strip()
        if direct_url:
            log.info(f"Using agent URL from .env: {direct_url}")
            self._agent_chat_url = direct_url
            return direct_url

        agent_name = os.getenv("TERPAI_AGENT_NAME", "Aether Study Assistant")
        raise TerpAIError(
            f"Agent '{agent_name}' lookup requires TERPAI_AGENT_URL in .env. "
            f"Open TerpAI, click your agent, copy the chat URL."
        )

    # ─── File Upload ──────────────────────────────────────────────────────

    async def _upload_attachment(self, content: str, filename: str = "aether_knowledge.txt") -> str:
        """
        Upload a text file as a knowledge attachment.

        POST /api/internal/attachments?attachmentType=CodeInterpreter&context=GptSystem
        Body: multipart/form-data with the file

        Returns the attachmentId.
        """
        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        log.info(f"Uploading knowledge file: {filename} ({len(content)} chars)...")

        # Build multipart form — no Content-Type header (httpx sets it with boundary)
        headers = self._headers(content_type=None)

        resp = await self._client.post(
            f"{TERPAI_API_URL}/internal/attachments",
            params={
                "attachmentType": "FileSearch",
                "context": "GptSystem",
            },
            headers=headers,
            files={
                "file": (filename, content.encode("utf-8"), "text/plain"),
            },
            timeout=60.0,
        )

        if resp.status_code == 401:
            raise TerpAILoginRequired("Token expired during file upload")
        if resp.status_code != 200:
            raise TerpAIError(f"File upload failed ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        attachment_id = data.get("attachmentId") or data.get("id")
        if not attachment_id:
            # Try to extract from response
            log.warning(f"Unexpected upload response: {data}")
            raise TerpAIError(f"Could not get attachmentId from upload response: {data}")

        log.info(f"File uploaded: {attachment_id}")
        return attachment_id

    # ─── Agent Config ─────────────────────────────────────────────────────

    def _build_config_body(
        self,
        config_state_id: str,
        name: str,
        system_prompt: str = "",
        attachment_ids: list[str] | None = None,
        enable_web_search: bool = False,
    ) -> dict:
        """
        Build the JSON body for PUT /api/internal/configStates/{id}.
        Schema reverse-engineered from the TerpAI NebulOne API.
        """
        capabilities = ["CodeInterpreter"]
        if enable_web_search:
            capabilities.append("WebSearch")

        attachments = []
        for aid in (attachment_ids or []):
            attachments.append({
                "attachmentId": aid,
                "attachmentType": "FileSearch",
                "attachmentContext": "GptSystem",
                "originalFileName": "aether_knowledge.txt",
                "id": aid,
            })

        return {
            "configStateId": config_state_id,
            "languageEngine": "Assistant",
            "gptSystemName": name,
            "gptSystemType": "User",
            "description": "",
            "introduction": "",
            "systemPrompt": _NEBULONE_DEFAULT_SYSTEM_PROMPT,
            "customSystemPrompt": system_prompt,
            "topP": 0.95,
            "frequencyPenalty": 0.0,
            "deploymentName": "gpt-4o",
            "maxTokens": 16384,
            "temperature": 0.5,
            "verbosity": None,
            "reasoningEffort": None,
            "hipaaCompliant": False,
            "isHidden": False,
            "capabilityTypes": capabilities,
            "restrictAnswerToInformationReturnedByTools": False,
            "dataSources": [],
            "attachments": attachments,
            "prompts": [],
            "brandKey": None,
            "guidelinesDocumentId": None,
            "chatAccessPolicyId": None,
            "publicEndpointConfiguration": None,
            "tokenLimitSettings": {
                "limitTokens": False,
                "tokensPerDay": 500000000,
                "tokensPerUserPerDay": 1000000,
                "thresholdTokensPerDayMessage": "You're nearing the daily usage limit for this Agent.",
                "thresholdTokensPerUserPerDayMessage": "You're nearing your daily usage limit for this Agent.",
                "limitReachedTokensPerDayMessage": "The daily usage limit has been reached for this Agent.",
                "limitReachedTokensPerUserPerDayMessage": "You've reached your daily usage limit for this Agent.",
            },
            "status": "Active",
            "userRoleIds": [],
        }

    async def _save_config(self, config_state_id: str, config_body: dict):
        """PUT /api/internal/configStates/{id} — save the agent configuration."""
        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        resp = await self._client.put(
            f"{TERPAI_API_URL}/internal/configStates/{config_state_id}",
            headers=self._headers(),
            json=config_body,
            timeout=30.0,
        )

        if resp.status_code == 401:
            raise TerpAILoginRequired("Token expired during config save")
        if resp.status_code not in (200, 204):
            raise TerpAIError(f"Config save failed ({resp.status_code}): {resp.text[:200]}")

        log.info(f"Config saved for configState {config_state_id}")

    async def _finalize_create(self, config_state_id: str) -> str:
        """
        POST /api/internal/configStates/{id}/createGptSystem
        Finalizes a new agent. Returns the gptSystemId.
        """
        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        resp = await self._client.post(
            f"{TERPAI_API_URL}/internal/configStates/{config_state_id}/createGptSystem",
            headers=self._headers(),
            content=b"",  # empty body
            timeout=30.0,
        )

        if resp.status_code == 401:
            raise TerpAILoginRequired("Token expired during agent creation")
        if resp.status_code != 200:
            raise TerpAIError(f"createGptSystem failed ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        gpt_system_id = data.get("gptSystemId")
        log.info(f"Agent created: gptSystemId={gpt_system_id}")
        return gpt_system_id

    async def _finalize_update(self, config_state_id: str):
        """
        PUT /api/internal/configStates/{id}/updateGptSystem
        Finalizes an update to an existing agent.
        """
        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        resp = await self._client.put(
            f"{TERPAI_API_URL}/internal/configStates/{config_state_id}/updateGptSystem",
            headers=self._headers(),
            content=b"",  # empty body
            timeout=30.0,
        )

        if resp.status_code == 401:
            raise TerpAILoginRequired("Token expired during agent update")
        if resp.status_code not in (200, 204):
            raise TerpAIError(f"updateGptSystem failed ({resp.status_code}): {resp.text[:200]}")

        log.info(f"Agent updated: configState {config_state_id}")

    async def _get_config(self, config_state_id: str) -> dict:
        """GET /api/internal/configStates/{id} — read back the full agent config."""
        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        resp = await self._client.get(
            f"{TERPAI_API_URL}/internal/configStates/{config_state_id}",
            headers=self._headers(),
            timeout=15.0,
        )

        if resp.status_code == 401:
            raise TerpAILoginRequired("Token expired")
        if resp.status_code != 200:
            raise TerpAIError(f"Config read failed ({resp.status_code}): {resp.text[:200]}")

        return resp.json()

    # ─── Create Topic Agent (full flow) ───────────────────────────────────

    async def create_topic_agent(self, agent_name: str, context_text: str) -> str:
        """
        Create a new focused agent for a specific topic:
          1. Generate a configStateId (UUID)
          2. Upload knowledge file as attachment
          3. PUT the agent config (name, system prompt, attachment, capabilities)
          4. POST createGptSystem to finalize
          5. Return the agent chat URL

        Raises TerpAIError on failure — caller handles gracefully.
        """
        if not self._ready:
            raise TerpAIError("TerpAI not ready, cannot create topic agent")

        log.info(f"Creating topic agent: '{agent_name}'...")

        async with self._lock:
            try:
                # 1. Create a new configState (TerpAI allocates the ID)
                create_resp = await self._client.post(
                    f"{TERPAI_API_URL}/internal/configStates/byGptSystemType/User",
                    headers=self._headers(),
                    content=b"",
                    timeout=15.0,
                )
                if create_resp.status_code not in (200, 201):
                    raise TerpAIError(f"configState creation failed ({create_resp.status_code}): {create_resp.text[:200]}")
                create_data = create_resp.json()
                config_state_id = (
                    create_data.get("configStateId")
                    or create_data.get("id")
                    or create_data.get("configuration", {}).get("configStateId")
                )
                if not config_state_id:
                    raise TerpAIError(f"No configStateId in create response: {create_data}")
                log.info(f"ConfigState ID: {config_state_id}")

                # 2. Embed context directly in the system prompt
                system_prompt = (
                    AETHER_SYSTEM_PROMPT +
                    f"\n\n[KNOWLEDGE CONTEXT]\n{context_text}\n[END KNOWLEDGE CONTEXT]\n\n"
                    "Answer questions using the knowledge context above. Be specific and accurate."
                )

                # 3. Build and save the agent config
                config_body = self._build_config_body(
                    config_state_id=config_state_id,
                    name=agent_name,
                    system_prompt=system_prompt,
                    attachment_ids=[],
                )

                await self._save_config(config_state_id, config_body)

                # 4. Finalize creation
                gpt_system_id = await self._finalize_create(config_state_id)

                agent_url = f"{TERPAI_BASE_URL}/chat/{gpt_system_id}"
                log.info(f"Topic agent '{agent_name}' created: {agent_url}")

                return agent_url

            except TerpAIError:
                raise
            except Exception as e:
                raise TerpAIError(f"Topic agent creation failed: {e}") from e

    # ─── Knowledge Context Update ────────────────────────────────────────

    async def update_agent_knowledge(self, context_text: str):
        """
        Update the current agent's knowledge source with fresh context.

        Flow:
          1. Read current agent config (GET configState)
          2. Upload new knowledge file
          3. Replace attachments in config
          4. PUT updated config
          5. PUT updateGptSystem to finalize
        """
        if not self._ready:
            log.warning("TerpAI not ready, skipping knowledge update")
            return

        # Hash check — skip if context hasn't changed
        new_hash = hashlib.md5(context_text.encode()).hexdigest()
        if new_hash == self._last_context_hash:
            log.info("Knowledge context unchanged, skipping update")
            return

        # We need the configStateId to update the agent
        config_state_id = self._agent_config_state_id or os.getenv("TERPAI_CONFIG_STATE_ID", "").strip()
        if not config_state_id:
            log.warning(
                "Cannot update agent knowledge: no configStateId available. "
                "Set TERPAI_CONFIG_STATE_ID in .env to the agent's config state ID. "
                "Find it in the agent edit URL: /chat/agents/configstate/{id}/edit"
            )
            return

        log.info(f"Updating agent knowledge context for configState {config_state_id}...")

        async with self._lock:
            try:
                # 1. Read current config
                full_config = await self._get_config(config_state_id)
                config = full_config.get("configuration", full_config)

                # 2. Upload new knowledge file
                attachment_id = await self._upload_attachment(
                    content=context_text,
                    filename="aether_knowledge_context.txt",
                )

                # 3. Replace attachments
                config["attachments"] = [{
                    "attachmentId": attachment_id,
                    "attachmentType": "FileSearch",
                    "attachmentContext": "GptSystem",
                    "originalFileName": "aether_knowledge_context.txt",
                    "id": attachment_id,
                }]

                # 4. Also ensure our system prompt is set
                config["customSystemPrompt"] = AETHER_SYSTEM_PROMPT

                # 5. Save config
                await self._save_config(config_state_id, config)

                # 6. Finalize update
                await self._finalize_update(config_state_id)

                self._last_context_hash = new_hash
                log.info("Agent knowledge updated successfully")

            except TerpAIError:
                raise
            except Exception as e:
                raise TerpAIError(f"Knowledge update failed: {e}") from e

    # ─── Conversation Management ─────────────────────────────────────────

    async def _ensure_conversation(self) -> str:
        """
        Get or create a conversation ID for the current agent.
        
        URL structure: /chat/{agentId}/{conversationId}
        If TERPAI_AGENT_URL includes a conversationId, use it.
        Otherwise, create a new conversation.
        """
        if self._conversation_id:
            return self._conversation_id

        # Try to extract from agent URL
        # Format: https://terpai.umd.edu/chat/{agentId}/{conversationId}
        if self._agent_chat_url:
            parts = self._agent_chat_url.rstrip("/").split("/")
            # /chat/{agentId}/{conversationId} → at least 2 parts after /chat/
            chat_idx = next((i for i, p in enumerate(parts) if p == "chat"), -1)
            if chat_idx >= 0 and len(parts) > chat_idx + 2:
                self._conversation_id = parts[chat_idx + 2]
                log.info(f"Using conversation ID from URL: {self._conversation_id}")
                return self._conversation_id
            # Only agentId in URL — need to create a conversation
            if chat_idx >= 0 and len(parts) > chat_idx + 1:
                self._agent_id = parts[chat_idx + 1]

        # Create a new conversation
        if self._agent_id:
            log.info(f"Creating new conversation for agent {self._agent_id}...")
            try:
                resp = await self._client.post(
                    f"{TERPAI_API_URL}/internal/userConversations",
                    headers=self._headers(),
                    json={"gptSystemId": self._agent_id},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._conversation_id = data.get("userConversationId") or data.get("id")
                    if self._conversation_id:
                        log.info(f"Created conversation: {self._conversation_id}")
                        return self._conversation_id
                    # If response doesn't have the ID, try the conversation ID from response
                    log.warning(f"Unexpected create conversation response: {data}")
                else:
                    log.warning(f"Create conversation returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                log.warning(f"Failed to create conversation: {e}")

        # Fallback: generate a UUID and hope the API creates it on-the-fly
        self._conversation_id = str(uuid.uuid4())
        log.warning(f"Using generated conversation ID: {self._conversation_id}")
        return self._conversation_id

    # ─── Send Prompt (core messaging) ────────────────────────────────────

    async def send_prompt(self, prompt: str, timeout_seconds: int = 60) -> str:
        """
        Send a prompt to the TerpAI agent and return the full response.

        API contract (NebulOne platform):
          POST /api/internal/userConversations/{conversationId}/segments
          Body: {
            "question": "<prompt>",
            "lineage": {"parentSegmentId": "<last segment>", "lineageType": "Question"},
            "visionImageIds": [],
            "attachmentIds": [],
            "segmentTraceLogLevel": "NonPersisted"
          }
          Response: SSE stream — "response-updated:" events carry base64-encoded text chunks

        Raises TerpAIError on failure — caller should fall back to Gemini.
        """
        if not self._ready:
            raise TerpAIError("TerpAI bridge not ready")

        if not self._client:
            raise TerpAIError("HTTP client not initialized")

        conversation_id = await self._ensure_conversation()

        async with self._lock:
            try:
                log.info(f"Sending prompt ({len(prompt)} chars)...")

                body = {
                    "question": prompt,
                    "visionImageIds": [],
                    "attachmentIds": [],
                    "segmentTraceLogLevel": "NonPersisted",
                }

                # Add lineage if we have a previous segment
                if self._last_segment_id:
                    body["lineage"] = {
                        "parentSegmentId": self._last_segment_id,
                        "lineageType": "Question",
                    }

                chunks: list[str] = []

                async with self._client.stream(
                    "POST",
                    f"{TERPAI_API_URL}/internal/userConversations/{conversation_id}/segments",
                    headers=self._headers("application/json"),
                    json=body,
                    timeout=httpx.Timeout(timeout_seconds + 10, connect=10.0),
                ) as resp:
                    if resp.status_code == 401:
                        self._ready = False
                        raise TerpAILoginRequired(
                            "TerpAI token expired (401). Paste a fresh token in .env."
                        )
                    if resp.status_code != 200:
                        text = await resp.aread()
                        raise TerpAIError(
                            f"TerpAI API returned {resp.status_code}: {text[:200]}"
                        )

                    # Parse SSE stream
                    # Supports two formats:
                    #   Standard SSE: "event: response-updated\ndata: base64..."
                    #   Single-line:  "response-updated: base64..."
                    current_event = None
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            # Do not reset current_event here, TerpAI sometimes sends empty lines 
                            # between 'event' and 'data' lines!
                            continue

                        # Handle error events from TerpAI
                        if line.startswith("event:"):
                            current_event = line.split(":", 1)[1].strip()
                            if current_event == "not-found":
                                raise TerpAIError(
                                    "Conversation not found. Check TERPAI_AGENT_URL "
                                    "includes a valid conversation ID."
                                )
                            if current_event == "error":
                                raise TerpAIError("TerpAI returned an error event")
                            continue

                        # Standard SSE: "data: payload"
                        if line.startswith("data:"):
                            payload = line.split(":", 1)[1].strip()
                            if current_event == "response-updated":
                                try:
                                    decoded = base64.b64decode(payload).decode("utf-8")
                                    chunks.append(decoded)
                                except Exception as e:
                                    log.debug(f"Skipping malformed chunk '{payload}': {e}")
                            elif current_event == "response-model":
                                try:
                                    model_data = json.loads(
                                        base64.b64decode(payload).decode("utf-8")
                                    )
                                    seg_id = model_data.get("conversationSegmentId")
                                    if seg_id:
                                        self._last_segment_id = seg_id
                                except Exception:
                                    pass
                                break  # Stream is complete
                            continue

                        # Single-line format: "response-updated: base64..."
                        if line.startswith("response-updated:"):
                            b64_data = line.split(":", 1)[1].strip()
                            try:
                                decoded = base64.b64decode(b64_data).decode("utf-8")
                                chunks.append(decoded)
                            except Exception as e:
                                log.debug(f"Skipping malformed chunk: {e}")

                        elif line.startswith("response-model:"):
                            try:
                                b64_model = line.split(":", 1)[1].strip()
                                model_data = json.loads(
                                    base64.b64decode(b64_model).decode("utf-8")
                                )
                                seg_id = model_data.get("conversationSegmentId")
                                if seg_id:
                                    self._last_segment_id = seg_id
                            except Exception:
                                pass
                            break  # Stream is complete

                if not chunks:
                    raise TerpAIError("TerpAI returned empty response (no chunks)")

                full_response = "".join(chunks)
                log.info(f"Got response ({len(full_response)} chars)")
                return full_response

            except TerpAIError:
                raise
            except httpx.TimeoutException:
                raise TerpAIError(f"TerpAI response timed out after {timeout_seconds}s")
            except Exception as e:
                raise TerpAIError(f"send_prompt failed: {e}") from e


    # ─── Specialized Agent Context Cache ────────────────────────────────────

    def store_agent_context(self, agent_url: str, context_doc: str):
        """Cache the knowledge document for a specialized agent URL."""
        self._agent_contexts[agent_url] = context_doc
        log.info(f"Stored context for agent {agent_url.split('/')[-1]} ({len(context_doc)} chars)")

    def get_agent_context(self, agent_url: str) -> str | None:
        """Return the cached knowledge document for a specialized agent, or None."""
        return self._agent_contexts.get(agent_url)

    # ─── Send Prompt to Specialized Agent ───────────────────────────────────

    async def send_prompt_to_agent(self, agent_url: str, prompt: str, timeout_seconds: int = 60) -> str:
        """
        Send a prompt in the context of a specialized agent.

        TerpAI does not expose a programmatic API for creating new conversations,
        so we route through the main Aether agent and inject the specialized
        knowledge document as a preamble in the prompt.
        """
        context_doc = self._agent_contexts.get(agent_url)
        if context_doc:
            # Prepend the specialized knowledge doc so the main agent answers
            # as if it were the specialized agent.
            enriched_prompt = (
                f"[SPECIALIZED CONTEXT — answer using this knowledge document]\n"
                f"{context_doc}\n"
                f"[END SPECIALIZED CONTEXT]\n\n"
                f"{prompt}"
            )
            log.info(
                f"Routing specialized agent request through main agent "
                f"(+{len(context_doc)} chars context)"
            )
        else:
            # No cached context — fall through to main agent without extra context
            enriched_prompt = prompt
            log.warning(
                f"No cached context for agent {agent_url.split('/')[-1]} — "
                f"using main agent without specialized context"
            )

        return await self.send_prompt(enriched_prompt, timeout_seconds=timeout_seconds)



# ─── Singleton Instance ────────────────────────────────────────────────────────

bridge = TerpAIBridge()
