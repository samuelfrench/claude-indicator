# TODO task-file migration — 2026-10-07

Original: `TODO.md` at `d857694a050ddfb8774ce99be64e774ded5d9426`; 70 lines; SHA-256 `c6a17a1833366be14ae0f5c269a2235227fb4638b3dfb18a1fc5af390dfd2e55`. All original non-empty lines are preserved in task files or completed archive. The four original open checkboxes remain verbatim in three task files. Historical commands are preserved for audit and are not authorization to run provider or infrastructure actions.

| Original line | Destination |
|---|---|
| 11 | [product/claude-header-limitations.md](product/claude-header-limitations.md) |
| 12 | [product/claude-header-limitations.md](product/claude-header-limitations.md) |
| 26 | [infra/child-notify-socket.md](infra/child-notify-socket.md) |
| 27 | [product/grok-missing-meter.md](product/grok-missing-meter.md) |
| 44 | [infra/legacy-source-zone-hold.md](infra/legacy-source-zone-hold.md) |
| 64 | [product/session-notification-ideas.md](product/session-notification-ideas.md) |
| Remaining lines | `TODO-archive.md#pre-task-files-2026-10-07` |

**Proof command:** `git show d857694:TODO.md > /tmp/indicator-old-TODO.md`; create an empty `/tmp/indicator-archive-base.md`; run `node scripts/todo/migrate-monolith.mjs verify /tmp/indicator-old-TODO.md . /tmp/indicator-archive-base.md`. The verifier compares non-empty line multiplicities; checkbox comparison separately verifies every original open item.

**Privacy cleanup:** Subsequent beta cleanup redacts private/unrelated history from the current public tree. The zero-loss proof applies to migration commit `130efb9`, not the cleaned tree. To audit the original proof, create an isolated temporary checkout of that commit and run the verifier there. The removed source-zone task was unrelated infrastructure work and is retained only in the owner-local restricted backup and Git history.
