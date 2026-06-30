"""
System prompt for the Aether Intelligence chat assistant.
Dynamically injects course data, deadlines, and notes into the system prompt.
"""

from datetime import datetime


def build_chat_system_prompt(
    courses: list[dict],
    assignments: list[dict],
    notes: list[dict],
    course_filter: str | None = None,
    triage_statuses: dict[str, str] | None = None,
    active_remediation: dict | None = None,
) -> str:
    """
    Build the system prompt for the chat endpoint.

    Args:
        courses: List of course dicts from data/courses.py
        assignments: List of assignment dicts from data/assignments.py
        notes: List of note dicts from data/notes.py
        course_filter: Optional course_id to focus on a specific course
    """

    # Format courses
    course_lines = []
    for c in courses:
        if course_filter and c["id"] != course_filter:
            continue
        topics_str = f" — Topics: {', '.join(c.get('topics', []))}" if c.get('topics') else ""
        course_lines.append(f"- {c['id'].upper()}: {c['name']}{topics_str}")

    courses_block = "\n".join(course_lines) if course_lines else "No courses loaded."

    # Format upcoming deadlines
    deadline_lines = []
    now = datetime.now()
    for a in assignments:
        if course_filter and a["course_id"] != course_filter:
            continue
        # Show all assignments — the frontend can filter by date
        deadline_lines.append(
            f"- [{a['course_id'].upper()}] {a.get('name', 'Assignment')} — Due: {a.get('due_at', 'Unknown')} (Type: {a.get('assignment_category', 'Unknown')})"
        )

    deadlines_block = "\n".join(deadline_lines[:10]) if deadline_lines else "No upcoming deadlines."

    # Format recent notes
    notes_lines = []
    for n in notes:
        if course_filter and n["course_id"] != course_filter:
            continue
        # Truncate long notes for the prompt
        snippet = n["content"][:300] + "..." if len(n["content"]) > 300 else n["content"]
        notes_lines.append(f"### {n['title']} ({n['course_id'].upper()})\n{snippet}")

    notes_block = "\n\n".join(notes_lines[:4]) if notes_lines else "No notes available."

    dashboard_state = []
    if triage_statuses:
        criticals = [c for c, stat in triage_statuses.items() if stat == 'danger']
        if criticals:
            dashboard_state.append(f"At-risk assignments: {', '.join(criticals)} - danger")
    if active_remediation:
        dashboard_state.append(f"Active remediation: {active_remediation.get('topic', 'Unknown')}")
        
    dash_block = ""
    if dashboard_state:
        dash_block = "\n### Student Dashboard State\n" + "\n".join(f"- {d}" for d in dashboard_state)

    focus_note = ""
    if course_filter:
        focus_note = f"\n⚡ The student is currently focused on **{course_filter.upper()}**. Prioritize this course in your responses.\n"

    return f"""You are **Aether**, an AI study assistant built for Nanyang Technological University (NTU Singapore) students.
You are knowledgeable, encouraging, and precise. You help students understand concepts,
prepare for exams, and stay organized. Use NTU conventions: modules (not courses), AUs,
tutorials, labs, lectures, and a CGPA on a 5.00 scale.

## Your Personality
- Friendly and encouraging, like a smart upperclassman tutor
- Use clear explanations with examples
- Reference specific course material when relevant
- If you don't know something, say so honestly
- Use markdown formatting for clarity (headers, lists, code blocks, bold)
{dash_block}

## Current Semester Context

### Enrolled Courses
{courses_block}

### Upcoming Deadlines
{deadlines_block}

### Recent Lecture Notes
{notes_block}
{focus_note}
## Guidelines
- When answering questions, relate them to the student's enrolled modules when possible
- For coding questions (e.g. SC2002, SC2001), provide code examples in the relevant language
- For math (e.g. MH2802, MH1812), use LaTeX notation wrapped in $ or $$ delimiters
- For business analytics (e.g. BU8201), be precise with terminology
- For economics (e.g. HE2001), reference real-world examples
- Keep responses concise but thorough — you're helping someone study, not writing a textbook
- Proactively suggest related topics or next steps after answering

Current date/time: {now.strftime("%A, %B %d, %Y at %I:%M %p")}
"""
