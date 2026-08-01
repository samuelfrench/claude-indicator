# Smart TODO Dismiss Design

**Date:** 2026-07-31

## Outcome

Every open Smart TODO row gets a `Dismiss` button. Dismiss means “finished in the command center,” not Markdown completion: it must not change `[ ]` to `[x]`, and it must not edit any global or project TODO source file.

Dismissed tasks disappear from `Focus`, `All open`, and `Waiting`, stop contributing to open/focus/urgent/overdue/waiting counts, and remain inspectable in a new `Finished` view. Completed inbox tasks retain their existing `Completed inbox` view and semantics.

## Persistence

Add a focused `FinishedStore` in `smart_todos.py`, injected into `SmartTodoDialog` through `finished_store_path` and defaulting to `~/.claude/smart_todos_finished.json`. The JSON format is `{"version": 1, "finished": ["stable-key", ...]}`. Writes use a same-directory temporary file, flush, `fsync`, mode `0600` for a new file, preservation of an existing regular file's mode, and `os.replace`. The store rereads before every write, fails closed on malformed or unsafe state, and never stores task text.

Managed inbox tasks use `managed:<managed-id>` as their stable key. Other tasks use `source:<sha256>` over the absolute source path, heading path, and normalized display text. That identity survives line-number movement while avoiding plaintext task data in the sidecar. A source edit creates a new active task, which is the safe default because it may represent materially new work.

## UI and Data Flow

`TodoItem` gains `finished: bool = False`. After each scan, the dialog reads finished keys and applies the flag before summaries and rendering. A malformed state file produces a visible warning and leaves tasks active.

`TodoTaskRow` emits a task-valued `dismiss_requested` signal and renders `Dismiss` only when the task is open and not already finished. The dialog persists the stable key, marks the matching in-memory item finished, recomputes the summary, and rerenders immediately without rescanning every TODO file. Write failure leaves the item visible and reports the error inline.

The `Finished` view contains dismissed open tasks from every source. Finished rows retain `Open source` but have no `Dismiss` or `Complete` control. The Why Now rail says the task was finished in the command center. No restore control is added in this change.

## Verification

Tests must prove the state key behavior, atomic/mode-safe JSON persistence, malformed-state fail-closed behavior, source TODO byte preservation, summary exclusion, view membership, button availability, immediate UI transition, error handling, and compact 860x680 layout. The full Pytest suite, `py_compile`, offscreen interaction smoke, and live tray dialog must pass before push and restart.

No hosted model, dependency, public endpoint, external service, or billable operation is added.
