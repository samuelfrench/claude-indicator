# Smart TODO Command Center Design

**Date:** 2026-07-31

## Purpose

Add a local-first task command center to Claude Indicator. It must let Sam capture overall tasks in `/home/sam/TODO.md`, continuously read project `TODO.md` files under `/home/sam/claude-workspace` and `/home/sam/codex_workspace`, and explain which work deserves attention now.

The command center does not call a hosted model. Its ranking is deterministic, fast, inspectable, and free to run. Existing project TODO files are read-only; only the command center's managed section in `/home/sam/TODO.md` is mutated.

## User Experience

The system tray uses a new task-compass icon: a warm-gold ring, a white check stroke, and a violet priority needle. Its menu gains `Smart TODOs…` above the existing widget visibility action. Activating that action opens one modeless dialog, so Claude Indicator continues refreshing in the background.

The dialog is a dark, restrained command center rather than a generic form. Its signature element is the `Why now` rail: every ranked task shows a score, urgency band, project, due state, and a short plain-language explanation such as `overdue by 3 days · P0 section · billing risk`. The header shows open, overdue, urgent, and waiting counts.

The top capture row accepts a task and an optional due date. `Add task` atomically appends an unchecked item to a clearly delimited `## Indicator Inbox` section in `/home/sam/TODO.md`. Empty tasks are rejected inline. The item immediately appears in the ranked list without restarting the app.

Controls provide text search, project filter, and view filters for `Focus`, `All open`, `Waiting`, and `Completed inbox`. Double-clicking a result opens its source file at the task line with the system's configured editor. Managed inbox tasks expose a completion control; discovered project tasks never do. A refresh action rescans disk immediately.

## Visual Direction

The dialog extends the existing translucent widget without copying generic dashboard styling.

- `Midnight glass` `#14141E`: window field.
- `Graphite panel` `#20202D`: task rows and controls.
- `Warm signal` `#D4A574`: headings and task-compass ring.
- `Priority violet` `#8B5CF6`: focus selection and compass needle.
- `Deadline coral` `#F87171`: overdue and critical state.
- `Quiet ink` `#B4B4C8`: secondary copy.

Typography uses the platform sans-serif in three explicit roles: 17px semibold display, 12px task copy, and 10px uppercase utility labels with letter spacing. The hierarchy comes from score and explanation, not ornamental cards. Motion is limited to selection, refresh state, and dialog reveal; reduced-motion users receive no animation.

## Architecture

Create `smart_todos.py` as a focused domain and UI module. This avoids adding another responsibility to the existing 3,796-line `claude_widget.py` while keeping the app dependency-free beyond PySide6.

The module contains four bounded units:

1. `TodoScanner` discovers and reads TODO files with depth and size limits, parses Markdown checkboxes plus their heading path, and returns typed `TodoItem` values and scan warnings.
2. `TodoRanker` classifies due dates, explicit priorities, blockers, revenue/billing risk, verification work, waiting/future gates, owner-only action, and staleness. It returns a score, urgency band, tags, and ordered `why_now` reasons. Future-gated or explicitly waiting tasks are separated from the actionable focus queue instead of being falsely promoted by urgent vocabulary.
3. `InboxStore` owns only the delimited Indicator Inbox section of `/home/sam/TODO.md`. It uses same-directory temporary files plus `os.replace()` for atomic writes, preserves unrelated content byte-for-byte, assigns stable HTML-comment IDs to managed entries, and supports add and complete operations.
4. `SmartTodoDialog` renders capture, summary, filters, task rows, source navigation, completion, refresh, loading, empty, and warning states. A `TodoScanWorker` runs discovery and ranking on a `QThread` so multi-megabyte TODO files cannot freeze the tray.

`claude_widget.py` creates one lazy dialog instance, adds the tray menu action, and refreshes the tray tooltip with the latest focus/overdue summary. Closing the dialog hides and reuses it; quitting the tray app closes its worker safely.

## Discovery and Parsing

Workspace roots default to `/home/sam/claude-workspace` and `/home/sam/codex_workspace`; the overall file defaults to `/home/sam/TODO.md`. Tests can inject all paths and today's date.

Discovery walks no deeper than three directories below each project root and skips `.git`, `.worktrees`, `node_modules`, `dist`, `build`, `target`, caches, virtual environments, Playwright output, and hidden directories. Resolved file paths are deduplicated. Files are read as UTF-8 with replacement and capped at 4 MiB; an oversized or unreadable file produces a visible warning and does not abort other projects.

The parser recognizes `- [ ]`, `* [ ]`, `- [x]`, and `* [x]`, retains the complete heading path, source line, source path, and project name, strips display-only Markdown, and extracts ISO dates when introduced by `due`, `by`, `on`, `target`, or `date`. A bare historical date does not automatically become a deadline.

## Ranking Model

Open tasks start with a base score. Signals add or subtract fixed weights:

- Explicit P0, critical, urgent, immediate, blocker, launch, or deploy context.
- P1, revenue, customer, checkout, traffic, outreach, money, billing, paid, or cost context.
- Production verification, live validation, indexing, GSC, GA4, smoke, or test context.
- Exact due date proximity, with overdue tasks receiving the largest date boost.
- Heading priority and global-inbox origin.
- Explicit waiting, hold, blocked-by-owner, `on or after`, `no earlier than`, or a future gate date; these are tagged `waiting` and withheld from `Focus` until actionable.
- Completed items score zero and appear only in `Completed inbox` when owned by the managed section.

The score is not presented alone. `why_now` lists the strongest non-duplicated reasons in descending impact. Stable tie-breaking uses due date, project, source path, and line number. The dialog displays up to 250 rows per view while summary counts cover the complete scan.

## Persistence and Mutation Safety

The managed section is delimited by exact comments:

```markdown
<!-- claude-indicator:inbox:start -->
## Indicator Inbox

- [ ] Example task <!-- claude-indicator:id=... -->
<!-- claude-indicator:inbox:end -->
```

If absent, the section is appended after one normalized blank-line boundary. On every mutation, `InboxStore` rereads the current file, validates that there is at most one complete marker pair, changes only text inside that pair, writes a temporary sibling, flushes and `fsync()`s it, preserves the original mode, then atomically replaces the destination. Broken or duplicate markers fail closed with a visible error. No project TODO file can be edited through this feature.

User-entered text is normalized to one Markdown line by collapsing line breaks and whitespace. A due date is stored as `due: YYYY-MM-DD`. IDs use UUID4 and are never derived from task text. Completion targets the exact managed ID, preventing line-number drift from changing the wrong item.

## Error Handling

Unreadable roots and files become non-blocking warnings in the dialog. A global-file write failure keeps the typed task in the input and shows the exact actionable error. Marker corruption disables add/complete until repaired; it never rewrites ambiguous content. Source opening failures show an inline status message. Worker results are ignored after the dialog is destroyed.

## Testing and Verification

Unit tests use temporary directories and literal Markdown fixtures to prove discovery exclusions, heading parsing, explicit-date parsing, waiting gates, score ordering, reasons, size/read warnings, marker initialization, preservation of unrelated bytes, atomic add, exact-ID completion, and fail-closed corrupted markers. Every production behavior follows red-green-refactor.

Qt tests run offscreen and exercise dialog capture, validation, filters, read-only versus managed completion, refresh, and tray action reuse. Tests use real widgets and real temporary files; only OS source launching and the system tray boundary are patched.

Completion requires:

1. Full `pytest` and `py_compile` pass.
2. An offscreen Qt interaction smoke test with no Qt/runtime exceptions.
3. A real desktop launch with the dialog opened, add/filter/complete/refresh exercised against an isolated temporary TODO root, screenshots reviewed at readable resolution, and widget log checked for new exceptions.
4. The production app restarted from its configured autostart command and its single live PID verified.
5. Commit and push to `master`, followed by remote SHA equality and GitHub Actions verification if this repository has a workflow.

## Billing and Security

The feature adds no dependency, network call, subscription, hosted inference, telemetry, or public endpoint. It does not read secrets or memory files. Existing Anthropic usage polling remains unchanged. Source navigation uses a local process only and never executes task text as a command.
