# Atlas Command Center Redesign: Right-Stacked Layout

## Overview
We are redesigning the main Atlas Command Center to feel much more spacious and modern.

---

## New Layout Proposal (Right-side stacked panels)

### Left
Keep the vertical Wheel Navigation (HOME / COMMAND CENTRAL / CALENDAR) exactly as it is from previous phases. It should remain slim and always visible.

---

### Center
The main hero area — make this significantly wider and more spacious.

- Place a large, elegant **Morning Brief** glass card in the upper-center.
- Below it, leave generous empty space with a very subtle dark radial gradient or soft mesh background for depth.
- The center should feel calm and focused, similar to the large welcome area in the “Script” AI interface screenshot.

---

### Right Side
A single tall column (~360px wide) that contains both information sources stacked vertically:

#### Top Half (~50% height): Autonomous Triage Panel
- Header: **“AUTONOMOUS TRIAGE”** + item count
- Scrollable list of assignments with:
  - Clean spacing
  - Course pills
  - Truncated titles
  - Time ago
  - Status badges (Healthy/Danger using pastel red accent)

#### Bottom Half (~50% height): Announcements Panel
- Header: **“ANNOUNCEMENTS”** + count
- Scrollable list of announcements with:
  - Clean card spacing
  - Title
  - Course
  - Time ago

---

### Bottom
Persistent full-width bar containing:
- Chat input (“Ask Atlas anything…”)
- Course filters
- Toggles (THERMAL, PREREQS, RESET)
- Mastery slider

---

## Spacing & Aesthetic Goals (inspired by the Script interface)

- Use generous whitespace everywhere — especially in the center column.
- Increase padding between elements (24–32px gaps).
- Make side panels feel lighter and less dense:
  - Softer backgrounds
  - Increased item spacing
  - Subtle borders
- Keep glassmorphism but with higher translucency (`bg-white/[0.04]` or `[0.06]`).
- Use the pastel red accent sparingly and intentionally (mainly for danger indicators and key buttons).
- The overall feel should be calm, premium, and focused:
  - The center is the star
  - The right column provides supporting information without overwhelming the screen

---

## Technical Changes

- Update the main layout in:
  - `pages/CommandCenter.tsx`
  - `components/layout/PageShell.tsx`

- The right column should:
  - Use `flex-col`
  - Contain two equal (or near-equal) flex children for:
    - Triage panel
    - Announcements panel

- Ensure both right panels are independently scrollable if content overflows.

- Keep the WheelNav on the left untouched.

---

## Goal
A clean, airy, modern intelligence hub where the center has maximum breathing room.