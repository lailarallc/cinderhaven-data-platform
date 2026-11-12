## Design System

Read `../lailara-design-system/LAILARA_DESIGN_SYSTEM.md` before any visual work — colors, typography, layout, components, charts, voice, interactions. It is the single source of truth.

---
# Cinderhaven Data Platform — Project Context for Claude

## What this project is

Modern data platform for a fictional $25M specialty food brand — the
warehouse substrate that powers every downstream analytical portfolio
piece. Demonstrates source-to-mart pipelines, data quality testing,
orchestration, and lineage for CPG data shapes (product master, EDI,
retailer transactions, deductions, POS). Primary audience is technical
reviewers (client CTO/data lead, fractional CTO, hiring manager).

**Business question this project answers:** Can the practice build
real data infrastructure, not just analytical scripts on bundled files?

Tier: Heavy

## Stack and tools

Stack not yet locked in. To be determined during /clarify.

## Project files

- CLAUDE.md (this file) — permanent rules and facts
- DECISIONS.md — durable choices and reasoning
- HANDOFF.md — current session state
- PLAN.md — current work arc
- FAILURES.md — things tried that didn't work
- docs/solutions/ — documented solutions to past problems (bugs, integration issues, workflow patterns), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`)

Read PLAN.md and HANDOFF.md at session start. DECISIONS.md and
FAILURES.md as relevant.

## Voice and standards

- Economist style for written deliverables: sober, declarative,
  data-forward
- No marketing voice or consultant filler ("leverage," "synergy,"
  "best-in-class," "unlock," "drive value")
- No hedging that softens a real finding
- Charts must be readable by non-data-scientist, non-researcher
  audiences

## Rules

### Honesty and judgment

- Say "I don't know" or "I can't verify this" instead of guessing.
  This applies to industry context, technical claims, what code did,
  and anything else.
- Tell me what I need to hear, not what I want to hear. If a decision
  looks wrong, say so. If code I wrote has problems, say so. Honest
  assessment, not validation.
- If a rule in this file is too vague to verify whether you're
  following it, flag it for revision rather than guessing at compliance.

### Building and proposing

- No speculative abstractions. If something isn't needed right now,
  don't build it. Helper functions get added when called by real code,
  not in anticipation. Parameters get added when there's a second use
  case, not the first.
- When proposing a tool, library, or approach, present at least two
  alternatives with tradeoffs, even if one is clearly preferred. Do
  not propose a single solution and move on. The default failure mode
  is taking the route with less friction instead of the route that
  best fits the project — challenge yourself before proposing.
- Tie proposals back to the business question this project is
  answering. If you can't connect a proposal to that question, the
  proposal is probably fluff and should be reconsidered.

### How to work the project

- Work in vertical slices, not horizontal phases. Build one section
  end-to-end (data → analysis → visualization → prose) before moving
  to the next. Visualizations should be reviewed and adjusted in their
  own slice, not deferred to a polish phase at the end.
- Do not start tasks outside the current PLAN.md arc without flagging
  it to the user first.
- Do not refactor unrelated code unprompted.
- Do not rename things unless asked.
- A test command that gates a commit, a push or a recorded result runs
  unpiped or under `set -o pipefail`, and the gate reads the test
  runner's own exit code. Never `test | tail && git commit`: `tail`
  exits 0. Trim output only in a separate command (FAILURES.md,
  2026-11-11).

## Working with PLAN.md

PLAN.md defines the current arc of work. Read it at session start.

- Mark tasks complete as they're finished, in the same commit as the
  work
- If a task is wrong-sized, in the wrong order, or no longer relevant,
  flag it rather than silently restructuring
- "Out of scope" items are decisions, not suggestions — do not pull
  them into the current arc without explicit user approval

## Session reminders

### Reminding the user to /log

Prompt the user to run /log when:

- A meaningful change just landed (file written, bug fixed, feature
  added, decision made)
- A natural pause point is reached (about to switch tasks, finished a
  chunk of work)
- Roughly 30-45 minutes have passed since the last /log and real work
  has happened since then

Format as a clearly separated note. Do not nag — one suggestion per
trigger.

### Reminding the user to /wrap

Prompt the user to run /wrap when:

- Context usage crosses 65%
- The user says anything that suggests they're stopping
- A natural milestone is reached
- 90+ minutes have passed and work is winding down

Format as a clearly separated note. Do not nag.

### Session start protocol

1. Read CLAUDE.md, PLAN.md, and HANDOFF.md
2. If HANDOFF.md's most recent entry is more than 24 hours old AND
   there are uncommitted changes, flag this — the previous session
   may have ended without /wrap
3. Briefly state the starting point from HANDOFF.md so the user
   confirms you're caught up
4. Confirm the current PLAN.md arc is still active

## Defaults

- Default to flagging gaps rather than filling with plausible-sounding
  but unverified content
- Default to short responses unless the task is substantive
- Default to asking before promoting a log entry to a DECISIONS.md
  entry
- Default to answering, not offering to answer
