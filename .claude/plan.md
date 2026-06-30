# Atlas Intelligence — Sprint 2 Plan

## Context

Phase 1 is complete: dashboard (CommandCenter), 3D knowledge graph (NeuralLattice), AI chat (Atlas Ghost-Pilot + Gemini fallback), study artifacts (flashcards/quiz/study-guide via StudyLab modal), voice (ElevenLabs TTS + browser fallback). This sprint adds the features that connect everything together and make it demo-worthy — plus two new external agent integrations: **Exa** (course search + scraping) and **ZO** (email agent).

**Time remaining:** ~8-12 hours of hackathon.

---

## What's Already Built

- **Frontend:** CommandCenter, NeuralLattice (3D force graph w/ thermal + prereq modes), Chat modal, StudyLab modal, FlashcardDeck, QuizMode, StudyGuideView, InspectorPanel (Study/Ask AI buttons do nothing yet), ControlDock (thermal/prereq toggles)
- **Backend:** Atlas Ghost-Pilot (Playwright), Gemini context builder, all `/api/generate/*` routes, SSE streaming chat, file parsing, graph extraction, voice TTS
- **Stores:** useAppStore (courses, assignments, concepts, connections, flashcards, quizQuestions, studyGuide), useCommandStore (systemStatus, triageStatuses, activeRemediation)
- **Mock data:** 4 NTU courses, 46 assignments, 38 concepts, 33 connections, lecture notes, syllabi

---

## New External Agent Integrations (This Sprint)

### Exa Search Engine
Exa replaces manual Playwright scraping for course discovery. It provides semantic search over academic content, enabling Atlas to fetch real NTU course syllabi, module descriptions, and related resources on demand.

- **Endpoint:** `POST /api/exa/search-courses`
- **Use cases:** Scrape NTU STARS module catalog, fetch course prerequisite trees, pull lecture/reading resources by topic keyword
- **Owner:** Person 2 (backend)

### ZO Email Agent
ZO is a specialized email agent that monitors the student's NTU email for announcements, deadline reminders, and professor messages. It surfaces digested summaries into the CommandCenter Announcements panel and triggers triage updates.

- **Endpoint:** `POST /api/zo/sync` + webhook listener
- **Use cases:** Parse NTU email announcements → Announcements panel, detect deadline changes → triage re-score, send daily brief digest via email
- **Owner:** Person 2 (backend) + Person 4 (frontend wiring)

---

## Priority Tiers

| Tier | Features | Why |
|------|----------|-----|
| **Must Ship** | Artifacts in chat, mastery tracking, AI context awareness, graph filtering, Exa course search | Core demo loop — graph ↔ chat ↔ study tools all connected; Exa powers live course data |
| **Should Ship** | ZO email sync → Announcements panel, node→artifact mapping, week/overview graph views, Gemini graph→knowledge doc | Strengthens Atlas Agent Showdown + Data Viz prizes; ZO makes triage feel live |
| **Nice to Have** | Calendar view, voice commands, ZO daily brief email, day-specific agents | Polish |

---

## Person 1 — Frontend UI (Chat Artifacts + Inspector Wiring + Calendar)

### Owns (modified)
- `frontend/src/pages/Chat.tsx` — render artifacts inline in messages
- `frontend/src/components/graph/InspectorPanel.tsx` — wire Study/Ask AI buttons
- `frontend/src/App.tsx` — add Calendar route
- `frontend/src/components/layout/Sidebar.tsx` — add Calendar nav link

### Owns (new)
- `frontend/src/components/chat/ArtifactRenderer.tsx` — detects JSON in chat messages, renders interactive artifacts
- `frontend/src/components/chat/InlineFlashcards.tsx` — compact flashcard deck for chat bubbles
- `frontend/src/components/chat/InlineQuiz.tsx` — compact quiz for chat bubbles
- `frontend/src/components/chat/InlineStudyGuide.tsx` — markdown render for chat bubbles
- `frontend/src/pages/Calendar.tsx` — month grid showing assignments by due date

### Tasks (priority order)

**P0: Artifact detection + inline rendering in chat**
- `ArtifactRenderer.tsx`: try `JSON.parse(content)` — if has `cards` key → InlineFlashcards; if has `questions` key → InlineQuiz; if markdown with `##` headers → InlineStudyGuide; else plain text
- Only attempt detection when message is complete (not during streaming)
- Replace `<pre>` in Chat.tsx (line 104) with `<ArtifactRenderer content={msg.content} />`
- Inline components are compact versions of existing FlashcardDeck/QuizMode

**P1: Wire InspectorPanel Study/Ask AI buttons**
- Study → reads `pendingStudyTopic` from store (Person 3 adds), opens StudyLab pre-filled
- Ask AI → reads `pendingChatPrompt` from store, opens Chat with "Explain {concept.label}"
- Needs Person 3's store additions as dependency

**P2: ZO Announcements panel wiring (stretch)**
- Pull `zoAnnouncements` from store (Person 2 populates via ZO sync)
- Render in CommandCenter Announcements panel with course tag + time ago

**P3: Calendar page (stretch)**
- Month-grid with assignment chips, color-coded by course

### Deps: Person 3's store additions (pendingChatPrompt, pendingStudyTopic, conceptArtifacts); Person 2's ZO sync store population

---

## Person 2 — Backend AI (Context Injection + Exa + ZO + Knowledge Pipeline)

### Owns (modified)
- `backend/models/schemas.py` — extend ChatRequest with triage/system state fields
- `backend/routers/chat.py` — forward command center state to prompt builder
- `backend/prompts/context_builder.py` — inject student dashboard state into Atlas prompts
- `backend/prompts/chat_system.py` — inject state into Gemini fallback prompt
- `backend/main.py` — register new routers (knowledge.py, mastery.py, exa.py, zo.py)

### Owns (new)
- `backend/routers/exa.py` — POST `/api/exa/search-courses`, GET `/api/exa/module/{code}`
- `backend/services/exa_client.py` — Exa SDK wrapper, query builder for NTU module catalog
- `backend/routers/zo.py` — POST `/api/zo/sync`, webhook endpoint for incoming email events
- `backend/services/zo_client.py` — ZO agent API wrapper, email digest parser
- `backend/routers/knowledge.py` — POST `/api/knowledge/refresh-from-graph`
- `backend/prompts/graph_analysis.py` — Gemini prompt to analyze graph JSON → knowledge doc

### Tasks (priority order)

**P0: AI context awareness**
1. Extend `ChatRequest` in schemas.py:
   ```python
   triage_statuses: Optional[dict[str, str]] = None
   system_status: Optional[dict[str, str]] = None
   active_remediation: Optional[dict] = None
   upcoming_deadlines: Optional[list[dict]] = None
   ```
2. In context_builder.py, inject into Atlas prompt:
   ```
   [STUDENT DASHBOARD STATE]
   At-risk assignments: Quiz 4 Data Structures (SC1007) - danger
   Active remediation: Quiz 4 Data Structures - step 1/4
   Deadlines next 7 days: CE2006 Project 3 (2 days)
   Low mastery concepts: Dynamic Programming (40%)
   [END STATE]
   ```
3. In chat.py, pass new fields through to prompt builders

**P1: Exa course search integration**
1. `exa_client.py`: initialize Exa SDK, implement `search_courses(query, num_results=5)` and `fetch_module(code)` — returns title, description, prerequisites, reading list
2. `exa.py` router:
   - `POST /api/exa/search-courses`: accepts `{ query, course_level? }` → calls Exa → returns structured module list
   - `GET /api/exa/module/{code}`: fetches detailed module info for graph enrichment
3. Wire into knowledge pipeline: after graph construction, enrich concept nodes with Exa-fetched reading resources

**P2: ZO email agent integration**
1. `zo_client.py`: ZO API wrapper — `sync_inbox()` returns list of `{ subject, from, course_tag, summary, timestamp, type: 'announcement'|'deadline'|'grade' }`
2. `zo.py` router:
   - `POST /api/zo/sync`: triggers ZO inbox scan → parses results → returns announcements + any triage-affecting deadline changes
   - `POST /api/zo/webhook`: receives ZO push events for real-time updates
3. Deadline-change events re-score triage (call existing triage logic with updated deadlines)

**P3: Gemini graph analysis → knowledge doc**
- `POST /api/knowledge/refresh-from-graph`: accepts graph JSON (concepts+mastery+connections), Gemini analyzes → produces knowledge doc → uploads to Atlas via `bridge.update_agent_knowledge()`
- `graph_analysis.py`: formats concepts as `[label (course, mastery%)]` + connections

**P4: Day-specific Atlas context (stretch)**
- `day_focus` parameter filters context to assignments due within ±2 days

### Deps: Person 4 sends triage/system state from frontend

---

## Person 3 — Data + State + Graph Logic

### Owns (modified)
- `frontend/src/types/index.ts` — new types (MasteryUpdate, GraphFilters, ZOAnnouncement, ExaModule, etc.)
- `frontend/src/store/useAppStore.ts` — mastery tracking, artifact storage, graph filters, modal wiring state, ZO announcements, Exa module cache
- `frontend/src/hooks/useGraphData.ts` — filtering by course/mastery/view mode
- `frontend/src/hooks/useWeekGraph.ts` — current-week auto-detection
- `frontend/src/hooks/useMockData.ts` — add timestamps to concepts, load syllabi (NTU course codes)
- `frontend/src/components/graph/KnowledgeGraph.tsx` — consume filter state, view modes
- `frontend/src/components/graph/ControlDock.tsx` — course chips, mastery slider, view mode tabs
- `frontend/src/components/study/QuizMode.tsx` — call mastery tracker on results

### Owns (new)
- `frontend/src/hooks/useMasteryTracker.ts` — mastery update logic from quiz results
- `frontend/src/hooks/useGraphFilters.ts` — centralized graph filtering
- `frontend/src/hooks/useExaModules.ts` — fetch + cache Exa course search results
- `frontend/src/hooks/useZOSync.ts` — poll ZO sync endpoint, push announcements into store

### Tasks (priority order)

**P0: Mastery tracking (Skyrim skill tree)**
1. Add to types: `MasteryUpdate { conceptId, delta, source, timestamp }`, add `created_at/updated_at` to Concept
2. Add to store: `masteryHistory`, `updateConceptMastery(conceptId, delta, source)`, `conceptArtifacts` (maps concept IDs to generated artifacts), `pendingChatPrompt`, `pendingStudyTopic`
3. `useMasteryTracker.ts`: takes quiz results + topic → finds matching concepts by fuzzy label match → correct: +5 mastery, wrong: -3 mastery, clamped 0-100
4. Wire into QuizMode.tsx results screen — thermal graph colors update live

**P1: Graph filtering**
1. Add to store: `graphFilters { courseIds, masteryRange, viewMode: 'full'|'week'|'overview' }`
2. `useGraphFilters.ts`: pipeline courseIds → masteryRange → viewMode (week uses syllabi, overview collapses to 1 node per course)
3. Update `useGraphData.ts` to consume filters
4. `ControlDock.tsx`: course toggle chips, mastery slider, Full/Week/Overview tabs

**P2: ZO + Exa store integration**
1. Add to types: `ZOAnnouncement { id, subject, courseName, summary, timestamp, type }`, `ExaModule { code, title, description, prerequisites, resources }`
2. Add to store: `zoAnnouncements: ZOAnnouncement[]`, `setZOAnnouncements()`, `exaModuleCache: Record<string, ExaModule>`, `cacheExaModule()`
3. `useZOSync.ts`: polls `/api/zo/sync` every 60s, merges new announcements into store
4. `useExaModules.ts`: on-demand fetch of `/api/exa/search-courses`, caches results by query

**P3: Week graph auto-detection**
- `useWeekGraph.ts`: `currentWeek = ceil((now - semesterStart) / 7days)`, clamp 1-15

### Deps: None (starts first, unblocks Person 1 + Person 4)

---

## Person 4 — Voice + Integration (YOU)

### Owns (modified)
- `frontend/src/hooks/useChat.ts` — fix duplicate key bug (lines 48-52), inject command center state
- `frontend/src/hooks/useVoiceChat.ts` — add voice command preprocessing
- `frontend/src/lib/voice-controller.ts` — command detection patterns

### Owns (new)
- `frontend/src/hooks/useVoiceCommands.ts` — voice command parser
- `frontend/src/components/voice/VoiceFeedback.tsx` — visual voice state indicator
- `frontend/src/components/dashboard/ZOAnnouncementsPanel.tsx` — renders ZO-sourced announcements in CommandCenter
- `backend/routers/mastery.py` — POST `/api/mastery/update`

### Owns (existing)
- `backend/routers/voice.py`
- `backend/services/elevenlabs_tts.py`
- `frontend/src/hooks/useVoice.ts`
- `frontend/src/components/chat/VoiceReadout.tsx`
- `frontend/src/components/dashboard/DailyBrief.tsx`

### Tasks (priority order)

**P0: Fix useChat.ts + inject command center state**
1. Fix duplicate key bug — lines 48-52 send `messages` and `course_context` twice
2. Import `useCommandStore`, inject triage/system state:
   ```typescript
   const res = await apiPostRaw("/chat", {
     messages: allMessages,
     course_context: activeCourseId ?? undefined,
     triage_statuses: useCommandStore.getState().triageStatuses,
     system_status: useCommandStore.getState().systemStatus,
     active_remediation: useCommandStore.getState().activeRemediation,
   });
   ```
   Coordinate with Person 2's ChatRequest schema changes.

**P1: Mastery update endpoint**
- `backend/routers/mastery.py`: `POST /api/mastery/update` with `{ concept_id, delta, source }`
- Thin endpoint (frontend store is source of truth for hackathon)
- Tell Person 2 to add `app.include_router(mastery.router, prefix="/api")` in main.py

**P2: ZO Announcements panel (frontend)**
- `ZOAnnouncementsPanel.tsx`: subscribes to `zoAnnouncements` from store (Person 3's `useZOSync` populates it)
- Renders course-tagged announcement cards with summary + timestamp
- Wire into CommandCenter right column Announcements section (replaces mock announcements)

**P3: Voice commands for graph navigation**
- `useVoiceCommands.ts`: intercepts voice transcripts before sending to chat
  - "Show me {course}" → sets graph filter to that course (use NTU module codes e.g. SC1015, CE2006)
  - "Filter low mastery" → masteryRange [0, 50]
  - "Quiz me on {topic}" → opens StudyLab
  - "Check my emails" → triggers ZO sync
  - Anything else → send to chat normally
- In `useVoiceChat.ts`, preprocess through command detection first

**P4: Voice feedback component (stretch)**
- `VoiceFeedback.tsx`: floating indicator with waveform animation for active voice state

### Deps
- Person 2's schema changes (field names for P0), Exa/ZO routers registered in main.py
- Person 3's store additions (graph filter actions for P3, zoAnnouncements for P2)

---

## Coordination Timeline

```
Hour 0-2: Everyone parallel on independent pieces
  P1: ArtifactRenderer, InlineFlashcards, InlineQuiz (self-contained)
  P2: schemas.py changes, context_builder.py injection, exa_client.py + zo_client.py skeletons
  P3: types + store additions (incl. ZOAnnouncement, ExaModule), useMasteryTracker
  P4: Fix useChat.ts, build mastery.py endpoint, ZOAnnouncementsPanel skeleton

Hour 2-4: Integration phase 1
  P1: Wire ArtifactRenderer into Chat.tsx
  P2: Wire context injection in chat.py, finish exa.py router + test Exa search
  P3: Wire mastery into QuizMode, build useGraphFilters, useZOSync skeleton
  P4: Add command store injection to useChat.ts, wire ZOAnnouncementsPanel to store

Hour 4-6: Integration phase 2
  P1: Wire InspectorPanel buttons, wire ZO announcements display
  P2: Finish zo.py router + webhook, test ZO sync, build knowledge.py router
  P3: ControlDock filter UI, KnowledgeGraph wiring, useExaModules hook
  P4: Voice commands (incl. "check my emails" → ZO), wire into useVoiceChat

Hour 6-8: Polish + stretch
  P1: Calendar view
  P2: Day-specific Atlas context, Gemini graph analysis
  P3: Overview graph mode, Exa node enrichment via useExaModules
  P4: VoiceFeedback.tsx, ZO daily brief email trigger, final testing
```

---

## File Ownership (No Overlaps)

| File | Owner |
|------|-------|
| `frontend/src/pages/Chat.tsx` | Person 1 |
| `frontend/src/components/graph/InspectorPanel.tsx` | Person 1 |
| `frontend/src/components/chat/ArtifactRenderer.tsx` (new) | Person 1 |
| `frontend/src/components/chat/InlineFlashcards.tsx` (new) | Person 1 |
| `frontend/src/components/chat/InlineQuiz.tsx` (new) | Person 1 |
| `frontend/src/components/chat/InlineStudyGuide.tsx` (new) | Person 1 |
| `frontend/src/pages/Calendar.tsx` (new) | Person 1 |
| `frontend/src/App.tsx` | Person 1 |
| `frontend/src/components/layout/Sidebar.tsx` | Person 1 |
| `backend/routers/chat.py` | Person 2 |
| `backend/prompts/context_builder.py` | Person 2 |
| `backend/prompts/chat_system.py` | Person 2 |
| `backend/models/schemas.py` | Person 2 |
| `backend/main.py` | Person 2 |
| `backend/routers/exa.py` (new) | Person 2 |
| `backend/services/exa_client.py` (new) | Person 2 |
| `backend/routers/zo.py` (new) | Person 2 |
| `backend/services/zo_client.py` (new) | Person 2 |
| `backend/routers/knowledge.py` (new) | Person 2 |
| `backend/prompts/graph_analysis.py` (new) | Person 2 |
| `frontend/src/store/useAppStore.ts` | Person 3 |
| `frontend/src/types/index.ts` | Person 3 |
| `frontend/src/hooks/useGraphData.ts` | Person 3 |
| `frontend/src/hooks/useWeekGraph.ts` (new) | Person 3 |
| `frontend/src/hooks/useMockData.ts` | Person 3 |
| `frontend/src/hooks/useExaModules.ts` (new) | Person 3 |
| `frontend/src/hooks/useZOSync.ts` (new) | Person 3 |
| `frontend/src/components/graph/KnowledgeGraph.tsx` | Person 3 |
| `frontend/src/components/graph/ControlDock.tsx` | Person 3 |
| `frontend/src/components/study/QuizMode.tsx` | Person 3 |
| `frontend/src/hooks/useMasteryTracker.ts` (new) | Person 3 |
| `frontend/src/hooks/useGraphFilters.ts` (new) | Person 3 |
| `frontend/src/hooks/useChat.ts` | Person 4 |
| `frontend/src/hooks/useVoiceChat.ts` | Person 4 |
| `frontend/src/lib/voice-controller.ts` | Person 4 |
| `frontend/src/hooks/useVoiceCommands.ts` (new) | Person 4 |
| `frontend/src/components/voice/VoiceFeedback.tsx` (new) | Person 4 |
| `frontend/src/components/dashboard/ZOAnnouncementsPanel.tsx` (new) | Person 4 |
| `backend/routers/mastery.py` (new) | Person 4 |
| `backend/routers/voice.py` | Person 4 |
| `backend/services/elevenlabs_tts.py` | Person 4 |
| `frontend/src/hooks/useVoice.ts` | Person 4 |
| `frontend/src/components/chat/VoiceReadout.tsx` | Person 4 |
| `frontend/src/components/dashboard/DailyBrief.tsx` | Person 4 |

**Shared coordination:** Person 4 tells Person 2 to add `mastery.router`, `exa.router`, `zo.router` to main.py.

---

## Verification

1. **Chat artifacts**: Ask "give me flashcards on dynamic programming" → interactive cards render inline
2. **Mastery tracking**: Complete quiz → graph thermal colors update in real time
3. **Context awareness**: Ask "what should I study?" → AI references at-risk assignments + low mastery concepts
4. **Graph filtering**: Toggle courses (NTU module codes), slide mastery range → graph updates live
5. **Exa course search**: Ask "find resources for SC1015 data science" → Atlas fetches live module info via Exa
6. **ZO email sync**: Trigger ZO sync → NTU email announcements appear in CommandCenter Announcements panel
7. **Node→artifact**: Click concept → InspectorPanel Study → StudyLab opens pre-filled
8. **Knowledge pipeline**: Graph analysis → Gemini doc → uploaded to Atlas
9. **Voice commands**: Say "show me CE2006" → graph filters to that course; "check my emails" → ZO sync fires
