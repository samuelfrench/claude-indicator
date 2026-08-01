# Smart TODO Dismiss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent `Dismiss` action that marks an open Smart TODO finished without completing or editing its Markdown source.

**Architecture:** Extend the existing `smart_todos.py` domain/UI boundary with an atomic local `FinishedStore`, stable non-plaintext keys, a `TodoItem.finished` projection applied after scans, and row/dialog controls. Keep Markdown completion and read-only project-source rules unchanged.

**Tech Stack:** Python 3, PySide6, pytest, JSON, SHA-256, atomic `os.replace` persistence.

## Global Constraints

- `Dismiss` must never change a TODO checkbox or any TODO source bytes.
- Every open, non-finished task may be dismissed, including project tasks; completed or already-finished tasks may not.
- Dismissed tasks are excluded from all active views and summary counts and appear only in `Finished`.
- Finished state defaults to `~/.claude/smart_todos_finished.json` and is injectable in tests.
- Persist exactly `{"version": 1, "finished": ["stable-key", ...]}` with sorted unique keys and no task text.
- Managed keys are `managed:<managed-id>`; other keys are `source:<sha256>` of absolute path, heading, and display text separated by NUL bytes.
- State writes are same-directory, flushed, `fsync`ed, mode-safe, and finalized with `os.replace`; malformed or unsafe state fails closed.
- Keep the production dialog compact at 860x680 with zero horizontal scrolling.
- Add no dependency, network call, public endpoint, hosted inference, or billable service.

---

### Task 1: Persistent finished state and dismiss UI

**Files:**
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todos.py`
- Modify: `tests/test_smart_todo_ui.py`
- Modify: `README.md`
- Modify: `TODO.md`

**Interfaces:**
- Produces: `todo_finished_key(item: TodoItem) -> str`
- Produces: `FinishedStore(path: Path).read() -> frozenset[str]`
- Produces: `FinishedStore(path: Path).finish(item: TodoItem) -> None`
- Extends: `TodoItem.finished: bool = False`
- Extends: `SmartTodoDialog(..., finished_store_path: Path = Path.home() / ".claude" / "smart_todos_finished.json")`
- Extends: `TodoTaskRow.dismiss_requested: Signal(object)`

- [ ] **Step 1: Write failing domain tests**

Add real temporary-file tests proving literal managed/source keys, line-movement stability, source-edit identity change, sorted unique JSON without task text, reread-before-write, `0600` creation, existing-mode preservation, exact TODO byte preservation, `os.replace` as the final boundary, and rejection without mutation for malformed JSON, wrong version/schema, symlink, and non-regular paths.

- [ ] **Step 2: Run domain tests and verify RED**

Run `QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todos.py -k 'finished or dismiss'` and confirm failures are caused by the missing finished-state API.

- [ ] **Step 3: Implement the minimal domain behavior**

Add the immutable `finished` field, SHA-256 key builder, strict state reader, and atomic `FinishedStore.finish`. Do not change `InboxStore.complete` or project TODO handling.

- [ ] **Step 4: Run domain tests and verify GREEN**

Run the same focused domain command and require zero failures.

- [ ] **Step 5: Write failing UI tests**

Use real `SmartTodoDialog` widgets and temporary TODO/state files to prove: every active row has `Dismiss`; completed and finished rows do not; clicking project or managed dismissal preserves source bytes, writes the stable key, removes the item from active views/counts, and exposes it in `Finished`; a state-write failure leaves the row active with an inline error; a malformed state file warns and keeps tasks active; the finished Why Now copy is explicit; and production-shape rows keep zero horizontal overflow at 860x680.

- [ ] **Step 6: Run UI tests and verify RED**

Run `QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_smart_todo_ui.py -k 'finished or dismiss or 860x680'` and confirm failures are caused by missing UI behavior.

- [ ] **Step 7: Implement the minimal UI behavior**

Load finished keys after each scan, merge any state warning into the warning label, exclude finished items from active counts/views, add `Finished`, wire `Dismiss`, rerender immediately on success, preserve the selected task behavior, and show failures inline without changing in-memory state.

- [ ] **Step 8: Update user-facing documentation**

Document the `Dismiss` versus `Complete` distinction, the `Finished` view, and the local state path in `README.md`; mark this enhancement complete in `TODO.md`.

- [ ] **Step 9: Verify the task**

Run focused tests, then `QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q`, `/home/sam/miniconda3/bin/python3 -m py_compile claude_widget.py smart_todos.py`, and `git diff --check`.

- [ ] **Step 10: Commit**

Commit all task files with `feat: add Smart TODO dismiss state` and push the feature branch for review.
