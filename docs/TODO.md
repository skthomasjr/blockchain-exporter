# TODO

## Instructions

**Task Management:**

- Review the Task section before adding or editing items.
- Prioritize production readiness: maintainability, testability, performance, clarity.
- Items marked with `[?]` are requested for next work.
- Mark completed items with `[X]` after linting, testing, and verifying health/metrics endpoints.
- Refresh the Task list with the next highest-impact item once it becomes empty.

**Won't Do:**

Items listed in the "Won't Do" section have been considered and explicitly decided against. Do not implement these unless explicitly requested. This section helps avoid revisiting decisions and keeps focus on high-value work.

## Tasks

### High Priority (Production Readiness)

### Medium Priority (Architecture & Maintainability)

### Lower Priority (Testing & Reliability)

### Lower Priority (Features & Enhancements)

## Won't Do

- **WebSocket RPC connections**: HTTP RPC is sufficient for polling-based metrics collection. WebSocket adds significant complexity (connection management, reconnection logic, fallback handling) with marginal benefits for the current use case. The polling interval (typically 5+ minutes) doesn't require WebSocket's low-latency advantages. Most RPC providers have excellent HTTP support, while WebSocket support varies.

## Cleanup

- Normalized import grouping/whitespace across Python modules to maintain stdlib / third-party / local separation without broader reformatting.
- Refresh documentation (`README.md`, `docs/AI_REFERENCE.md`, `docs/TODO.md`) to reflect recent changes when directed.
- Polish code layout/formatting across the entire project (respect existing spacing/import conventions; avoid mass reformatting).
- Analyze test coverage to identify new or lingering gaps and propose targeted test additions.
- Review code comments/docstrings for consistency, clarity, and presence where needed; align style with existing conventions.
- Alphabetize non-functional enumerations (e.g., constant lists, `__all__`, documentation bullets, variable names, functions) where ordering has no semantic meaning to keep diffs tidy.
- Update the Task list according to the Instructions section (verify priorities, move completed items, surface the next high-impact work).
- Fix any outstanding Python linting issues reported by Ruff.
- Fix any Markdown linting issues reported by `mdformat --wrap=keep`.
- Fix any Dockerfile linting issues reported by Hadolint.
