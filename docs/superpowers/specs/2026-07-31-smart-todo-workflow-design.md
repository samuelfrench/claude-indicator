# Smart TODO Workflow Intelligence Design

**Date:** 2026-07-31

## Outcome

Turn the Smart TODO command center from a ranked backlog browser into a daily decision tool without becoming a project-management platform. The release includes all eight approved additions:

1. A seven-item Today queue with manual pinning.
2. Snooze until tomorrow, next week, or an exact date.
3. Restore from Finished.
4. New/Changed since the previous successful scan.
5. Exact duplicate grouping.
6. Per-project summaries with drill-down.
7. Copy Context for a ready-to-use Codex prompt.
8. Conservative stale review at 30, 60, and 90 days.

Everything remains local, deterministic, inspectable, and free to run. Project TODO files remain read-only. `/home/sam/TODO.md` remains the only TODO source that the Indicator may mutate, and only through its existing managed inbox boundary.

## Interaction Model

`Today` becomes the default view. It contains at most seven automatically ranked actionable tasks plus every active task Sam explicitly pins; pinned tasks appear first. Waiting, snoozed, completed, and finished tasks never enter Today automatically.

The view picker contains `Today`, `Focus`, `All open`, `Waiting`, `Snoozed`, `New / changed`, `Duplicates`, `Projects`, `Stale 30+`, `Stale 60+`, `Stale 90+`, `Completed inbox`, and `Finished`.

Task rows keep their existing compact source, complete, and dismiss controls. The selected task's Why Now rail gains a quiet action area with context-sensitive `Pin today`/`Unpin`, `Snooze…`/`Wake now`, `Copy context`, and Finished-only `Restore` controls.

Snooze opens a small native date dialog with `Tomorrow`, `Next week`, an exact `yyyy-MM-dd` date, `Snooze`, and `Cancel`. A task wakes at the start of its stored date: an entry snoozed until 2026-08-01 is active on 2026-08-01.

`Copy context` writes plain text to the desktop clipboard:

```text
Task: <full task text>
Project: <project>
Source: <absolute path>:<line>
Heading: <heading or None>
Due: <date or None>
Urgency: <band> (score <number>)
Why now:
- <reason>
```

Task text is copied as data only and is never executed.

## Visual Direction

The visual subject is a personal operating docket: a short ruled sheet for deciding what happens today, not a generic dashboard.

- `Midnight glass` `#14141E`: unchanged window field.
- `Graphite docket` `#20202D`: rows and rail.
- `Warm signal` `#D4A574`: Today numbering, pins, and headings.
- `Priority violet` `#8B5CF6`: selection.
- `Deadline coral` `#F87171`: overdue state.
- `Fresh mint` `#6FD0B0`: new/changed status.
- `Quiet ink` `#B4B4C8`: supporting copy.

The signature element is functional numbering: only Today rows receive a fixed-width `01` through `07` docket number, directly encoding execution order. Platform sans remains the display/body face for desktop consistency; compact metadata and docket numbers use the platform monospace face. Motion remains limited to ordinary control state changes.

The 860x680 production size remains mandatory. The action rail uses two-column button rows beneath Why Now, while task rows stay one line and horizontally scroll-free. Keyboard focus and accessible names describe every dynamic action and status.

## Persistent Workflow State

Keep the deployed `~/.claude/smart_todos_finished.json` version-1 schema unchanged. Add `FinishedStore.restore(item)`, using the same canonical-key validation, reread-before-write behavior, strict JSON parsing, mode handling, `fsync`, and atomic replacement already used by `finish`.

Store the other workflow state separately at `~/.claude/smart_todos_workflow.json`:

```json
{
  "version": 1,
  "pinned_today": ["managed:<id>"],
  "snoozed": [{"key": "source:<sha256>", "until": "2026-08-07"}],
  "observed": [{"location": "location:<sha256>", "content": "source:<sha256>", "unchanged_since": "2026-07-01"}]
}
```

The file contains no task text. Every list is sorted and unique. Parsing rejects duplicate JSON member names, unknown/missing fields, invalid versions, invalid key/date formats, duplicate/unsorted records, symlinks, and non-regular files. New files use mode `0600`; existing modes are preserved. Every mutation rereads, writes a same-directory temporary file, flushes and `fsync()`s it, then calls `os.replace()`.

Managed tasks use their validated `managed:<id>` content/location key. Project content keys reuse the existing `source:<sha256>` over absolute path, heading, and text. Project location keys use `location:<sha256>` over absolute path, heading, and line. Content keys survive line movement; location keys let the system distinguish an edit from a new entry.

## Scan Reconciliation

Each scanned item retains its source file's regular-file modification date. After a successful scan, workflow reconciliation compares current `(location, content)` observations with the previous snapshot:

- Same location and content: unchanged; retain `unchanged_since`.
- Same content at another location: moved; unchanged; retain the oldest matching date.
- Same location with different content: `changed`; reset `unchanged_since` to today.
- No location or content match: `new`; set `unchanged_since` to today.
- First-ever snapshot: no item is labeled new; seed `unchanged_since` from the source file's modification date, capped at today.

Only the immediately previous successful snapshot determines New/Changed. A second unchanged refresh clears those labels. If workflow persistence fails, the scan stays usable, shows a warning, and applies no new workflow state.

Snoozes whose date is today or earlier are pruned during successful reconciliation. Missing task keys remain stored in pinned/snoozed state so a temporarily absent source can return without losing the user's choice.

## Derived Intelligence

Today selection starts with active pinned tasks ordered by existing rank, then fills to seven with the highest-ranked unpinned actionable tasks. If more than seven tasks are pinned, all active pins remain visible; the UI reports the overage rather than discarding a choice.

Duplicates use a conservative exact normalized-text key: casefolded display text with collapsed whitespace. A duplicate group requires at least two open, non-finished items. The Duplicates view keeps every member visible, contiguous, and labeled `copy N of M`; actions still affect only the selected source identity.

Stale age is `today - unchanged_since`. On the first snapshot this is a conservative lower bound seeded from the TODO file modification date; later it is task-specific. Stale views exclude completed, finished, waiting, and snoozed tasks, and require no due date.

Project summaries include active, focus, waiting, snoozed, overdue, new/changed, duplicate, and stale-30 counts plus the highest-ranked active task. Selecting `Open queue` sets the project filter and opens that project's Focus view.

## Error and Safety Boundaries

- Workflow state corruption never hides, snoozes, pins, or labels a task; it becomes a visible warning.
- Failed pin/snooze/wake/restore writes leave in-memory state unchanged.
- Restore affects every current row sharing the same finished stable key, matching dismiss semantics.
- Copy Context failure is shown inline and never falls back to a shell or external process.
- Date selection rejects today/past dates for new snoozes.
- No action bulk-mutates duplicate groups.
- No notification, email, hosted model, cloud sync, network endpoint, dependency, subscription, or billable operation is added.

## Verification

Domain tests cover strict workflow JSON, atomic boundaries, permissions, reread-before-write, pin/snooze/wake, expiry, restore, snapshot reconciliation, moved/changed/new classification, duplicate grouping, Today selection, stale thresholds, and project summaries.

Offscreen Qt tests cover every view, default Today membership, docket numbering, action visibility, exact-date snooze, wake, pin/unpin, restore, Copy Context text, project drill-down, error preservation, keyboard accessibility, and 860x680 zero-overflow behavior with long production-shaped tasks.

Completion requires the full Pytest suite, `py_compile`, `git diff --check`, independent task and whole-branch reviews, a native-X11 isolated fixture exercising each mutation without touching real TODOs, and a real restarted tray dialog checked at 860x680 with no new service-log exceptions.
