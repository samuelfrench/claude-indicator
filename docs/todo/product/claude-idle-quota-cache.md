---
title: "Keep last-known Claude quotas visible while Claude Code is idle"
status: now
area: product
due: null
updated: 2026-11-02
owner: agent
brief: "Remove the premature five-minute expiry that hides valid quota snapshots."
refs: ["a68e080"]
test: null
---
- **What:** Retain local quota snapshots until each window resets, label cached age, preserve missing-window semantics and reject invalid timestamps.
- **Why:** Owner reports `Claude quota stale`; the real local snapshot is about 35,299 seconds old, contains weekly quota only and has not reached its reset. The previous five-minute bound incorrectly turns normal idle time into unavailable data.
- **Next:** Push, await green CI, restart existing user service and verify native widget. No provider requests, token changes or new billing.
- **Validation:** 15 focused local-feed checks (part of 569 tests plus 46 subtests in isolated HOME); all pass. TODO tests 25 passed, generated-state/diff checks passed and clean-install verifier passed. Independent review caught the reset boundary of already-loaded bars; display now checks each reset on every update. Cache preserves the original observation time and repeated polls do not duplicate graph observations.
- **Done:** Last-known weekly usage remains visible with accurate cached age; expired windows stay hidden, no artificial zero, no stale error for idle valid windows.
