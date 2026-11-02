---
title: "Keep last-known Claude quotas visible while Claude Code is idle"
status: done
area: product
due: null
updated: 2026-11-02
owner: agent
brief: "Remove the premature five-minute expiry that hides valid quota snapshots."
refs: ["df24ef2497832c83866e0c762016c68913710d78"]
test: null
---
- **What:** Retain local quota snapshots until each window resets, label cached age, preserve missing-window semantics and reject invalid timestamps.
- **Why:** Owner reports `Claude quota stale`; the real local snapshot is about 35,299 seconds old, contains weekly quota only and has not reached its reset. The previous five-minute bound incorrectly turns normal idle time into unavailable data.
- **Next:** None for Claude repair. Last-known usage remains explicitly cached; normal Claude Code activity supplies new observations.
- **Validation:** 15 focused local-feed checks (part of 569 tests plus 46 subtests in isolated HOME); all pass. TODO tests 25 passed, generated-state/diff checks passed and clean-install verifier passed. Independent review caught the reset boundary of already-loaded bars; display now checks each reset on every update. Cache preserves the original observation time and repeated polls do not duplicate graph observations.
- **Done:** Last-known weekly usage remains visible with accurate cached age; expired windows stay hidden, no artificial zero, no stale error for idle valid windows.

- **Deployed:** `df24ef2497832c83866e0c762016c68913710d78` pushed; Python/install CI `41452104525` and repository guards `41452104356` succeeded. User service restarted on November 2 at 07:22 CT (again 07:23 while restoring Grok). Native capture verified the weekly meter and footer `Claude Code cache · 9h 54m ago`; no quota-stale error. The original observation time is unchanged. Private capture `/tmp/claude-grok-quota-fix.png` is untracked.
