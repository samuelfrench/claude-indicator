# Smart TODO Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-only tray command center that atomically captures overall tasks in `/home/sam/TODO.md` and transparently ranks open tasks from every project TODO file by what needs attention now.

**Architecture:** A new `smart_todos.py` module owns Markdown parsing, bounded discovery, explainable ranking, mutation-safe inbox persistence, and the PySide6 dialog. `claude_widget.py` only integrates the lazy dialog, worker-safe shutdown, task-compass tray icon, menu action, and summary tooltip. Existing project TODO files remain read-only; only the exact managed section in the injected home TODO path can change.

**Tech Stack:** Python 3.10+, PySide6 6.6+, standard library (`dataclasses`, `datetime`, `pathlib`, `tempfile`, `uuid`, `os`, `re`, `shutil`, `subprocess`), pytest/unittest.

## Global Constraints

- Default workspace roots are exactly `/home/sam/claude-workspace` and `/home/sam/codex_workspace`; the default overall TODO is exactly `/home/sam/TODO.md`.
- Add no dependency, network call, subscription, hosted inference, telemetry, public endpoint, secret read, or memory-file scan.
- Project TODO files are read-only. Only entries with a `claude-indicator:id=<UUID>` inside the single valid Indicator Inbox marker pair may be completed.
- Marker corruption or duplication fails closed without modifying the file.
- Mutations reread current content, write a sibling temporary file, flush, `fsync()`, preserve mode, and replace atomically with `os.replace()`.
- Discovery depth is at most three below each project root, resolved paths are deduplicated, hidden/build/cache/worktree directories are skipped, and each file read is capped at 4 MiB.
- Scanning never blocks the Qt UI thread.
- Every score has ordered plain-language `why_now` reasons; future-gated and explicitly waiting items do not enter `Focus` before they are actionable.
- The dialog renders at most 250 result rows, while summary counts cover the complete scan.
- Use test-driven development: add each behavior test first, run it and see the expected failure, then add minimal production code.
- Run PySide6 tests with `QT_QPA_PLATFORM=offscreen`.
- Commit each task, push the completed feature to `master`, verify remote equality and Actions when present, then restart the production app from its configured autostart command.

## File Structure

- Create `smart_todos.py`: typed task model, parser, discovery, ranker, inbox store, source launcher, scan worker, task row, and command-center dialog.
- Create `tests/test_smart_todos.py`: real temporary Markdown fixtures and deterministic domain/persistence tests.
- Create `tests/test_smart_todo_ui.py`: real offscreen Qt dialog tests with temporary files; patch only tray/source-launch OS boundaries.
- Modify `claude_widget.py`: new icon factory, lazy dialog, tray menu action, tooltip summary, and shutdown.
- Modify `tests/test_widget_ui.py`: tray integration and icon/action/dialog-reuse tests.
- Modify `README.md`: feature, data sources, persistence ownership, ranking, and usage.
- Modify `TODO.md`: mark the Smart TODO command-center item complete after runtime verification.

---

### Task 1: Bounded TODO discovery, parsing, and explainable ranking

**Files:**
- Create: `smart_todos.py`
- Create: `tests/test_smart_todos.py`

**Interfaces:**
- Produces: `TodoItem`, `ScanResult`, `parse_todos(text, source_path, project, today)`, `discover_todo_files(workspace_roots)`, `rank_item(item, today)`, and `scan_todos(home_todo_path, workspace_roots, today=None)`.
- `TodoItem` is an immutable dataclass with exact fields: `id: str`, `text: str`, `completed: bool`, `source_path: Path`, `line: int`, `heading: str`, `project: str`, `due_date: date | None = None`, `managed_id: str | None = None`, `score: int = 0`, `urgency: str = "normal"`, `tags: tuple[str, ...] = ()`, `why_now: tuple[str, ...] = ()`, and `waiting: bool = False`.
- `ScanResult` is an immutable dataclass with exact fields: `items: tuple[TodoItem, ...]`, `warnings: tuple[str, ...]`, `scanned_files: int`, and `generated_at: datetime`.
- `scan_todos` returns all parsed items sorted by open-before-completed, waiting-after-actionable, descending score, due date, project, source path, and line.

- [ ] **Step 1: Write parser and discovery tests that name the breaks**

Add literal fixtures proving heading paths, Markdown stripping, managed IDs, explicit due-date extraction, bare historical dates not becoming deadlines, completed state, depth-three inclusion/depth-four exclusion, hidden/cache/build/worktree exclusion, resolved-path deduplication, and an oversized-file warning without aborting other files.

```python
def test_parse_todos_keeps_heading_path_and_only_explicit_due_dates():
    text = """# Product\n## P0 Launch\n- [ ] Ship live check due: 2026-08-02 <!-- claude-indicator:id=abc -->\n- [ ] Review evidence from 2026-07-20\n"""
    items = parse_todos(text, Path("/work/alpha/TODO.md"), "alpha", date(2026, 7, 31))
    assert items[0].heading == "Product > P0 Launch"
    assert items[0].due_date == date(2026, 8, 2)
    assert items[0].managed_id == "abc"
    assert items[1].due_date is None
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q`

Expected: collection fails because `smart_todos` does not exist.

- [ ] **Step 3: Implement the minimal typed parser and bounded discovery**

Use these exact constants and parser rules:

```python
MAX_TODO_BYTES = 4 * 1024 * 1024
MAX_TODO_DEPTH = 3
MAX_VISIBLE_ITEMS = 250
IGNORED_DIRS = frozenset({
    ".git", ".worktrees", ".next", ".pytest_cache", ".venv", ".wrangler",
    "__pycache__", "build", "coverage", "dist", "node_modules",
    "playwright-report", "target", "test-results", "venv",
})
TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MANAGED_ID_RE = re.compile(r"<!--\s*claude-indicator:id=([0-9A-Za-z-]+)\s*-->\s*$")
DUE_RE = re.compile(r"\b(?:due|by|on|target|date)\s*:?\s*(20\d{2}-\d{2}-\d{2})\b", re.I)
```

Read no more than `MAX_TODO_BYTES + 1` bytes. Decode with `errors="replace"`; if the extra byte exists, skip that file and emit `Skipped oversized TODO file: <path>`. Include the injected home TODO exactly once even when it is under a workspace root.

- [ ] **Step 4: Write ranker tests and verify RED**

Add table-driven tests with literal expected ordering and reasons for overdue, P0, P1/revenue, billing/cost, production verification, global inbox, explicit wait/hold, `on or after YYYY-MM-DD`, `no earlier than YYYY-MM-DD`, future due dates, same-day gates, and completed items.

```python
def test_future_gate_is_waiting_and_stays_out_of_focus_until_actionable():
    item = TodoItem(
        id="x", text="On or after 2026-08-22 evaluate GSC", completed=False,
        source_path=Path("/work/a/TODO.md"), line=1, heading="P0", project="a",
    )
    ranked = rank_item(item, date(2026, 7, 31))
    assert ranked.waiting is True
    assert ranked.urgency == "waiting"
    assert "gated until 2026-08-22" in ranked.why_now
```

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q`

Expected: parser/discovery tests pass and ranking tests fail because scoring is not implemented.

- [ ] **Step 5: Implement transparent ranking and full scanning**

Start open items at 20. Apply non-duplicated signals in this order, retaining the exact reason associated with each applied signal:

```python
SIGNALS = (
    (45, r"\bp0\b|highest|critical|urgent|immediate|blocker|launch|deploy", "critical priority signal"),
    (30, r"\bp1\b|revenue|money|growth|traffic|outreach|follow[ -]?up|customer|checkout", "revenue or customer impact"),
    (25, r"billing|paid|cost|subscription|charge", "billing or cost exposure"),
    (18, r"verify|validation|test|smoke|production|live|indexing|gsc|ga4", "production verification work"),
)
```

Date scoring is `+50` overdue, `+28` due today, `+20` due tomorrow, then `max(0, 14 - days_until_due)` for later dates. Global inbox items receive `+8` and reason `captured in overall inbox`. Explicit `waiting`, `wait for`, `hold`, `blocked by`, `owner action`, `Sam:`, `on or after`, and `no earlier than` language creates a waiting tag. An extracted future gate date creates reason `gated until YYYY-MM-DD`; waiting items have urgency `waiting` and sort after actionable open items regardless of score. Completed items score zero with urgency `completed`. Otherwise urgency is `critical` at 90+, `high` at 65+, and `normal` below 65. `why_now` contains at most four reasons, highest-impact first.

- [ ] **Step 6: Run domain tests and full baseline**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q && QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: all tests pass, including the original 30-test baseline.

- [ ] **Step 7: Commit Task 1**

```bash
git add smart_todos.py tests/test_smart_todos.py
git commit -m "feat: rank project TODOs locally"
```

---

### Task 2: Atomic managed inbox persistence and safe source navigation

**Files:**
- Modify: `smart_todos.py`
- Modify: `tests/test_smart_todos.py`

**Interfaces:**
- Consumes: `TodoItem` from Task 1.
- Produces: `InboxStore(path: Path)`, `InboxStore.add(text: str, due_date: date | None = None) -> str`, `InboxStore.complete(managed_id: str) -> None`, `normalize_task_text(text: str) -> str`, `source_open_command(item: TodoItem, which=shutil.which) -> list[str]`, and `open_source_item(item: TodoItem, popen=subprocess.Popen) -> None`.
- Exact markers are `<!-- claude-indicator:inbox:start -->` and `<!-- claude-indicator:inbox:end -->`.

- [ ] **Step 1: Write persistence tests first**

Use real temporary files to prove: missing file initialization; section append while preserving the entire original prefix; whitespace/newline normalization; due-date serialization; unique UUID marker creation; add after rereading an externally changed file; mode preservation; exact-ID completion; inability to complete an unmanaged project entry; duplicate, reversed, partial, or nested markers failing without byte changes; and `os.replace()` being the final mutation boundary.

```python
def test_complete_changes_only_the_exact_managed_id(tmp_path):
    path = tmp_path / "TODO.md"
    store = InboxStore(path)
    first = store.add("First")
    second = store.add("Second")
    store.complete(second)
    text = path.read_text()
    assert f"- [ ] First <!-- claude-indicator:id={first} -->" in text
    assert f"- [x] Second <!-- claude-indicator:id={second} -->" in text
```

- [ ] **Step 2: Run persistence tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q`

Expected: failures because `InboxStore` is not defined.

- [ ] **Step 3: Implement fail-closed atomic persistence**

`normalize_task_text` replaces CR/LF with spaces, collapses whitespace, strips checkbox/list prefixes and any `<!-- ... -->` fragment, and raises `ValueError("Enter a task before adding it.")` for empty output. Reject text longer than 500 characters with `ValueError("Tasks must be 500 characters or fewer.")`.

When the file is absent, treat its content as `"# TODO\n"` and its mode as `0o644`. Validate exactly zero markers or exactly one start followed by one end; every other count/order raises `ValueError("Indicator Inbox markers are incomplete or duplicated; no changes were written.")`. Use `tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)`, `flush()`, `os.fsync()`, `os.chmod()`, and `os.replace()`. On failure, unlink only the known temporary sibling.

- [ ] **Step 4: Write source-command tests and verify RED**

Test literal argument arrays for `code --goto`, `codium --goto`, `gedit +LINE`, and `xdg-open`, including paths with spaces. Assert no shell string is constructed and completed items use the same navigation behavior.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q`

Expected: persistence passes and source navigation fails because the functions are absent.

- [ ] **Step 5: Implement source navigation without shell execution**

Choose the first available command from `code`, `codium`, `gedit`, then `xdg-open`. Return exact lists: `[editor, "--goto", f"{path}:{line}"]`, `[editor, f"+{line}", str(path)]`, or `[editor, str(path)]`. If none is available, raise `RuntimeError("No local editor or file opener is available.")`. `open_source_item` calls injected `popen(command, start_new_session=True)` and never uses `shell=True`.

- [ ] **Step 6: Run domain tests and full suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todos.py -q && QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add smart_todos.py tests/test_smart_todos.py
git commit -m "feat: persist managed TODO inbox safely"
```

---

### Task 3: Smart TODO dialog and background scanning

**Files:**
- Modify: `smart_todos.py`
- Create: `tests/test_smart_todo_ui.py`

**Interfaces:**
- Consumes: `ScanResult`, `TodoItem`, `scan_todos`, `InboxStore`, and `open_source_item`.
- Produces: `TodoScanWorker(QThread)` with `result = Signal(object)` and `failed = Signal(str)`; `TodoTaskRow(QWidget)` with `complete_requested = Signal(str)` and `open_requested = Signal(object)`; `SmartTodoDialog(QDialog)` with `summary_changed = Signal(int, int)` where arguments are focus count and overdue count.
- `SmartTodoDialog.__init__` exact keyword-only injections: `home_todo_path: Path = Path.home() / "TODO.md"`, `workspace_roots: tuple[Path, ...] = (Path.home() / "claude-workspace", Path.home() / "codex_workspace")`, `today_provider: Callable[[], date] = date.today`, and `parent: QWidget | None = None`.
- Public methods: `refresh() -> None`, `shutdown() -> None`, and `show_and_refresh() -> None`.

- [ ] **Step 1: Write Qt behavior tests first**

With `QT_QPA_PLATFORM=offscreen`, use a real `QApplication`, real dialog, and temporary TODO roots. Prove initial loading state, refresh completion, summary counts over all items, 250-row render cap, `Focus` exclusion of waiting/completed tasks, `All open`, `Waiting`, `Completed inbox`, case-insensitive search, project filter, reset filters, selection explanation, add validation, successful add preserving input only on failure, completion only for managed rows, open-source signal routing, warning banner, empty state, and `shutdown()` waiting for an active worker.

```python
def test_focus_view_excludes_waiting_and_completed(qapp, tmp_path):
    dialog = make_dialog_with_fixture(tmp_path)
    dialog.show_and_refresh()
    wait_for_scan(dialog)
    assert visible_task_texts(dialog) == ["Overdue production check", "P1 customer task"]
```

- [ ] **Step 2: Run UI tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todo_ui.py -q`

Expected: collection or test failures because the UI classes do not exist.

- [ ] **Step 3: Implement worker and dialog structure**

Import the required Qt classes in `smart_todos.py`. Use `QDialog`, not `exec()`, and set `Qt.Tool | Qt.WindowStaysOnTopHint`. Minimum size is 760x620. Build one header summary, capture row (`QLineEdit`, `QDateEdit` with a `No due date` checkbox, `QPushButton("Add task")`), filter row (`QLineEdit`, project `QComboBox`, view `QComboBox`), `QScrollArea` task list, `Why now` detail rail, warning/status label, and refresh button. Apply the exact design colors through one module stylesheet.

Never call `scan_todos` from the UI thread. Disable refresh while a worker runs; on completion, store the full tuple, update summary counts, emit `summary_changed`, rebuild filters, and render at most `MAX_VISIBLE_ITEMS`. A second refresh request while active sets a pending flag and starts exactly one follow-up scan when the worker finishes.

- [ ] **Step 4: Implement capture, filtering, completion, and navigation**

`Focus` means open and not waiting. `All open` means open regardless of waiting. `Waiting` means open and waiting. `Completed inbox` means completed with `managed_id is not None`. Search covers text, project, heading, tags, and reasons. Completion controls exist only for managed open tasks. After add or complete, refresh from disk before reporting the new summary. Double-click or `Open source` calls `open_source_item`; exceptions set the status label and leave the dialog usable.

- [ ] **Step 5: Apply and critique the visual direction**

Use the design tokens exactly: `#14141E`, `#20202D`, `#D4A574`, `#8B5CF6`, `#F87171`, and `#B4B4C8`. Use 17px semibold display, 12px task copy, and 10px uppercase utility labels. The visible signature must be the `Why now` rail, not decorative gradients or generic statistic cards. Ensure visible keyboard focus, tab order, accessible names, high-contrast selected rows, and no animation requirement.

- [ ] **Step 6: Run UI, domain, and full suites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_smart_todo_ui.py tests/test_smart_todos.py -q && QT_QPA_PLATFORM=offscreen python -m pytest -q && python -m py_compile smart_todos.py claude_widget.py`

Expected: all tests and compilation pass with no runtime warnings introduced by the dialog.

- [ ] **Step 7: Commit Task 3**

```bash
git add smart_todos.py tests/test_smart_todo_ui.py
git commit -m "feat: add Smart TODO command center"
```

---

### Task 4: Tray integration, documentation, and production runtime proof

**Files:**
- Modify: `claude_widget.py`
- Modify: `tests/test_widget_ui.py`
- Modify: `README.md`
- Modify: `TODO.md`

**Interfaces:**
- Consumes: `SmartTodoDialog.summary_changed`, `show_and_refresh()`, and `shutdown()`.
- Produces: `build_task_compass_icon(size: int = 64) -> QIcon`; `ClaudeWidget._show_smart_todos()`, `ClaudeWidget._on_todo_summary_changed(focus_count: int, overdue_count: int)`, and a lazy `ClaudeWidget._smart_todo_dialog` reference.

- [ ] **Step 1: Write tray integration tests first**

Extend the inert widget helper to patch Smart TODO startup work. Prove the tray icon factory returns a non-null icon at 16, 32, and 64px; menu order is `Smart TODOs…`, `Show/Hide`, separator, `Quit`; triggering the action creates one dialog lazily; repeated triggers reuse and raise it; summary updates produce tooltip `Claude Indicator · <N> focus · <M> overdue`; tray-unavailable startup does not create the action; and close/application shutdown calls dialog `shutdown()` exactly once.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_widget_ui.py -q`

Expected: failures because task-compass and dialog integration are absent.

- [ ] **Step 3: Implement the tray feature**

Use QPainter to draw a warm-gold outer ring, dark inner field, white check stroke, and violet north-east needle. Replace the old purple `C` icon. Set the base tooltip to `Claude Indicator · Smart TODOs`. Add `QAction("Smart TODOs…", self)` before `Show/Hide`. Construct the dialog only on first activation, connect `summary_changed`, call `show_and_refresh()`, `raise_()`, and `activateWindow()`. In the application shutdown path, call dialog shutdown before worker teardown.

- [ ] **Step 4: Run integration and full automated verification**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_widget_ui.py -q && QT_QPA_PLATFORM=offscreen python -m pytest -q && python -m py_compile claude_widget.py smart_todos.py && git diff --check`

Expected: every test passes, both modules compile, and diff check is clean.

- [ ] **Step 5: Update user documentation and task state**

Document the tray action, capture flow, filters, ranking signals, workspace roots, read-only project boundary, Indicator Inbox marker ownership, local-only/no-billing behavior, and source navigation in `README.md`. Mark the Smart TODO item complete in `TODO.md` only after the runtime steps below succeed.

- [ ] **Step 6: Run isolated real-GUI interaction verification**

Create temporary workspace roots and home TODO data outside the repository. Launch a verification instance with an environment-controlled or small test harness injection so production files are not mutated. Use Playwright only where it can drive an exposed test surface; for the native PySide6 dialog, use QtTest or a focused GUI smoke harness to open the tray dialog, add a task, apply each filter, select a task, complete the managed entry, refresh, and close. Capture full-resolution screenshots with a filesystem image tool and inspect them only through a size-safe image viewer. Confirm no horizontal overflow, clipped copy, tiny unreadable UI, or new exceptions in the isolated log.

- [ ] **Step 7: Run the final completion audit**

Run fresh: `QT_QPA_PLATFORM=offscreen python -m pytest -q && python -m py_compile claude_widget.py smart_todos.py && git diff --check && git status --short`

Re-read the design and check every explicit requirement against current files and runtime evidence. Do not use the passing unit suite as proof of the real GUI or production restart.

- [ ] **Step 8: Commit, merge to master if needed, and push**

```bash
git add claude_widget.py smart_todos.py tests/test_widget_ui.py tests/test_smart_todos.py tests/test_smart_todo_ui.py README.md TODO.md docs/superpowers/specs/2026-07-31-smart-todo-command-center-design.md docs/superpowers/plans/2026-07-31-smart-todo-command-center.md
git commit -m "feat: ship Smart TODO tray command center"
git checkout master
git merge --ff-only feat/smart-todo-command-center
git push origin master
```

If already executing on `master`, omit checkout/merge and push the current verified commit. Confirm `git rev-parse HEAD` equals `git rev-parse origin/master` after a fresh fetch.

- [ ] **Step 9: Verify GitHub and restart the production app**

Check `.github/workflows`. If workflows exist, inspect the pushed SHA's Actions run through `gh`; wait for completion and require success. Stop only the exact currently running `/home/sam/miniconda3/bin/python3 /home/sam/claude-workspace/claude-indicator/claude_widget.py` PID, then launch the exact command from `/home/sam/.config/autostart/claude-widget.desktop`. Verify exactly one new PID, process age after the restart, the updated code path, visible main widget and Smart TODO dialog, task-compass tray availability, and no new exceptions in `~/.claude/widget.log`.

- [ ] **Step 10: Record durable state**

Add a terse memory update note under `/home/sam/.codex/memories/extensions/ad_hoc/notes/` with the pushed SHA, test count, production PID, scan roots, managed-section boundary, no-new-billing statement, and any ranking/UI gotcha worth reusing. Do not store task text from Sam's global TODO.
