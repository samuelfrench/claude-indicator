# Smart TODO Workflow Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Today, Snooze, Restore, New/Changed, duplicate, project-summary, Copy Context, and stale-review features as a local deterministic Smart TODO workflow.

**Architecture:** Preserve `smart_todos_finished.json` and add a strict generic workflow store in `smart_todo_workflow.py`. Keep task-specific enrichment and Qt rendering in `smart_todos.py`, using pure derivation functions tested before context-sensitive actions and aggregate views are wired.

**Tech Stack:** Python 3, PySide6, pytest, JSON, SHA-256, atomic `os.replace` persistence.

## Global Constraints

- Project TODO files remain read-only; only the managed Indicator Inbox in `/home/sam/TODO.md` may change through existing Add/Complete operations.
- The deployed `~/.claude/smart_todos_finished.json` version-1 format remains backward-compatible.
- New workflow state defaults to `~/.claude/smart_todos_workflow.json`, contains no task text, and is injectable in tests.
- Workflow JSON is strict, canonical, sorted, unique, duplicate-member rejecting, mode-safe, `fsync`ed, and atomically replaced.
- Workflow state failure leaves tasks active and exposes a warning.
- Today automatically contains seven actionable tasks plus every active pin; waiting, snoozed, completed, and finished tasks are excluded.
- Snoozed tasks wake when `today >= until`.
- Duplicate actions affect only the selected stable task identity, never the whole group.
- Stale views are conservative, undated, actionable, and thresholded at 30/60/90 days.
- Keep the production dialog at 860x680 with zero horizontal scrolling and accessible keyboard controls.
- Add no dependency, hosted model, network call, public endpoint, cloud sync, notification, subscription, or billable service.

---

### Task 1: Atomic workflow state and Finished restore

**Files:**
- Create: `smart_todo_workflow.py`
- Create: `tests/test_smart_todo_workflow.py`
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todos.py`

**Interfaces:**
- Produces: `TaskObservation(location: str, content: str, source_modified_on: date)`
- Produces: `ObservedTask(location: str, content: str, unchanged_since: date, change: str)`
- Produces: `WorkflowState(pinned_today: frozenset[str], snoozed: tuple[SnoozeRecord, ...], observed: tuple[ObservedRecord, ...])`
- Produces: `WorkflowStore(path: Path).read() -> WorkflowState`
- Produces: `WorkflowStore.pin(key)`, `unpin(key)`, `snooze(key, until)`, `wake(key)`, and `reconcile(observations, today) -> tuple[WorkflowState, dict[str, ObservedTask]]`
- Extends: `FinishedStore.restore(item: TodoItem) -> None`

- [ ] **Step 1: Write strict persistence tests and verify RED**

Add literal temporary-file cases for the exact empty schema, sorted unique pin/snooze/observed output, no task text, duplicate JSON names, missing/unknown fields, wrong version/types, invalid keys/dates, duplicate/unsorted records, symlink/FIFO rejection, `0600` creation, existing-mode preservation, external-change reread, `fsync`, and final `os.replace`. Add Finished restore cases proving one key removal, unknown-key rejection without byte change, and canonical output.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todo_workflow.py tests/test_smart_todos.py -k 'workflow or restore'
```

Expected RED: absent `smart_todo_workflow` and `FinishedStore.restore` APIs.

- [ ] **Step 2: Implement canonical persistence and verify GREEN**

Implement the interfaces above using duplicate-aware `json.loads`, explicit key regexes, no-follow/nonblocking reads, regular-file checks, same-directory temporary files, `flush`, `os.fsync`, mode `0600` or preservation, and `os.replace`. Every mutation rereads and validates first. Run the same command and require zero failures.

- [ ] **Step 3: Write reconciliation tests and verify RED**

Use hand-written observations to prove first baseline has empty change labels and source-mtime seeds, same-location unchanged, moved-content unchanged with oldest date, same-location edit changed today, unseen content new today, second unchanged reconciliation clears labels, expired snoozes prune at equality, future snoozes remain, and missing pin/snooze keys remain stored.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todo_workflow.py -k 'reconcile or snooze or pin'
```

Expected RED: missing reconciliation and workflow mutations.

- [ ] **Step 4: Implement reconciliation and verify the task**

Implement the exact design transitions without task-text persistence. Run focused tests, full Pytest, `py_compile`, and `git diff --check`.

- [ ] **Step 5: Commit and push**

```bash
git add smart_todo_workflow.py smart_todos.py tests/test_smart_todo_workflow.py tests/test_smart_todos.py
git commit -m "feat: persist Smart TODO workflow state"
git push -u origin feat/smart-todo-workflow
```

### Task 2: Deterministic workflow intelligence

**Files:**
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todos.py`
- Modify: `tests/test_smart_todo_workflow.py`

**Interfaces:**
- Consumes: Task 1 `WorkflowStore`, `TaskObservation`, and `ObservedTask`
- Extends: `TodoItem` with `source_modified_on`, `change_status`, `unchanged_since`, `snoozed_until`, `pinned_today`, `duplicate_key`, and `duplicate_count`
- Produces: `enrich_workflow(items, state, observed, today) -> tuple[TodoItem, ...]`
- Produces: `today_items(items, limit=7) -> tuple[TodoItem, ...]`
- Produces: `ProjectSummary(project, top_item, active, focus, waiting, snoozed, overdue, new_changed, duplicates, stale_30)`
- Produces: `project_summaries(items, today) -> tuple[ProjectSummary, ...]`

- [ ] **Step 1: Write enrichment tests and verify RED**

Prove scanner modification dates derive from the opened regular file's `st_mtime`, capped at today. Prove state maps to pins/snoozes/changes, finished precedence stays intact, expired snoozes are inactive, duplicate normalization is casefolded collapsed display text, exact groups get correct counts, and unique entries remain count one.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todos.py -k 'workflow or modified or duplicate'
```

Expected RED: missing fields and enrichment functions.

- [ ] **Step 2: Implement enrichment and verify GREEN**

Populate immutable fields with `replace`, keep stable sorting, and never change ranking scores because of workflow state. Run the same focused command.

- [ ] **Step 3: Write Today, stale, and project tests and verify RED**

Use literal fixtures to prove pins first, automatic fill to seven, pin overage retained, waiting/snoozed/completed/finished exclusion, stable tie-breaking, undated actionable stale membership at exactly 30/60/90 days, and exact project counts/top-item/sort order.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todos.py -k 'today_items or stale or project_summary'
```

Expected RED: absent derivation functions.

- [ ] **Step 4: Implement derivations, verify, commit, and push**

Run focused tests, full Pytest, `py_compile`, and diff-check, then:

```bash
git add smart_todos.py tests/test_smart_todos.py tests/test_smart_todo_workflow.py
git commit -m "feat: derive Smart TODO workflow intelligence"
git push
```

### Task 3: Context-sensitive workflow actions

**Files:**
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todo_ui.py`

**Interfaces:**
- Consumes: Task 1 store mutations and Task 2 item fields
- Produces: `SnoozeUntilDialog(selected_date: date, today: date)`
- Produces: `format_task_context(item: TodoItem) -> str`
- Extends: `SmartTodoDialog(..., workflow_store_path: Path = Path.home() / ".claude" / "smart_todos_workflow.json")`

- [ ] **Step 1: Write action-rail tests and verify RED**

Use real offscreen widgets to prove: no-selection actions hidden; active actionable shows Pin/Snooze/Copy; pinned shows Unpin; snoozed shows Wake/Copy; finished shows Restore/Copy; completed shows only Copy; all controls have exact accessible names and keyboard tab order.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todo_ui.py -k 'action_rail or pin or snooze or restore or copy_context'
```

Expected RED: absent controls and workflow-path injection.

- [ ] **Step 2: Implement action rail/date dialog and verify GREEN**

Add two compact button rows beneath Why Now. The dialog defaults to tomorrow, offers Tomorrow/Next week/exact date, rejects `until <= today`, and does nothing on Cancel. Render controls from immutable state. Run focused tests.

- [ ] **Step 3: Write mutation/clipboard tests and verify RED**

Prove pin/unpin, tomorrow/next-week/exact snooze, wake, and restore persist and update every same-key row immediately. Inject failing stores to prove rows/counts unchanged with inline errors. Assert the exact Copy Context literal in the clipboard and no process/shell invocation.

- [ ] **Step 4: Implement mutations, verify, commit, and push**

Update projections only after successful writes, recompute summary/render, and preserve selection when possible. Run focused tests, full Pytest, `py_compile`, and diff-check, then:

```bash
git add smart_todos.py tests/test_smart_todo_ui.py
git commit -m "feat: add Smart TODO workflow actions"
git push
```

### Task 4: Docket views, project summaries, and production layout

**Files:**
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todo_ui.py`
- Modify: `README.md`
- Modify: `TODO.md`

**Interfaces:**
- Consumes: Tasks 1-3 workflow state, derivations, and actions
- Produces: `ProjectSummaryRow(summary: ProjectSummary)` with `open_queue_requested: Signal(str)`
- Changes: `Today` is the default view and uses `01`–`07` docket numbering

- [ ] **Step 1: Write exact view-membership tests and verify RED**

Build one fixture containing active, waiting, snoozed, new, changed, duplicate, stale-30/60/90, completed, and finished tasks across projects. Assert exact membership/order for all thirteen view labels, Today's seven-item cap plus pin overage, duplicate contiguity and `copy N of M`, and Reset returning to Today.

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todo_ui.py -k 'view or docket or duplicate or stale or project'
```

Expected RED: missing view options and rendering branches.

- [ ] **Step 2: Implement views and docket numbering and verify GREEN**

Add the exact view labels. Today alone shows two-digit order using Warm signal and monospace styling. New/Changed uses Fresh mint metadata without changing ranking. Duplicates keep every source and annotate copy position. Run focused tests.

- [ ] **Step 3: Write project-summary/drill-down tests and verify RED**

Assert one row per project, exact counts/top task, keyboard/mouse selection, and `Open queue` setting project filter plus Focus. The empty Projects state must explain that no scanned projects have actionable tasks.

- [ ] **Step 4: Implement summaries and final layout and verify GREEN**

Render `ProjectSummaryRow` only for Projects, reuse Why Now for its top task, and hide task actions for summary selection.

- [ ] **Step 5: Add production-shape accessibility and overflow tests**

At exactly 860x680, use 1,500–3,000-character tasks, seven Today items, a managed three-button row, full action rail, every combo option, project summaries, and duplicate metadata. Assert horizontal scrollbar maximum `0`, row height at most `90`, button geometry containment, full tooltip/accessibility text, and successful keyboard actions.

- [ ] **Step 6: Update documentation and project TODO**

Document all views, state paths, Today rules, wake semantics, Restore, Copy Context, duplicate limits, conservative stale age, project drill-down, and local/billing boundary. Add one completed project TODO entry naming the full workflow release.

- [ ] **Step 7: Verify, commit, and push**

```bash
QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q
/home/sam/miniconda3/bin/python3 -m py_compile claude_widget.py smart_todos.py smart_todo_workflow.py
git diff --check
git add smart_todos.py tests/test_smart_todo_ui.py README.md TODO.md
git commit -m "feat: ship Smart TODO daily docket"
git push
```
