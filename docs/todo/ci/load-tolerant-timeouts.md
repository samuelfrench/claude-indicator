---
title: "Evidence-bound shared-machine test timeouts"
status: now
area: ci
due: null
updated: 2026-10-07
owner: agent
brief: "Task7: inspect load-sensitive failures, isolated per-project patches only where proven."
refs: []
test: null
---
- **What:** Read-only inventory across workspace projects, starting BBQ commit001fee3; patch only evidenced load-sensitive timeouts/retries in separate worktrees, each with its own small tested/rebased/pushed commit and generated project notes.
- **Why:** Concurrent self-hosted jobs can exceed narrow waits; unsupported blanket increases hide unrelated failures.
- **Next:** Independent review agent inventories exact CI/history evidence and current upstream fixes in `~/indicator-beta/task7-timeout-inventory.md`. Root executes accepted patches after the Indicator implementer finishes, avoiding primary-checkout active edits.
- **Authority:** Explicit task7 expands the original other-project restriction solely for timeout/retry changes. Roughly1.5–2× proven waits or at most1–2 known-flaky retries; retain assertions/checks. Never weaken Cigar production deployment verification, build the BBQ-owned machine-wide lock, touch other sessions, force-push, skip tests or alter runtime behavior.
- **External clocks:** Green existing CI and any deploy path depend on each project's current state; record exact code/live identities where applicable. No new services/billing.
- **Upstream:** No dependency patch or publication needed unless inventory proves a reusable third-party defect.
- [ ] Inventory recent failures/current fixes and active files for BBQ, Cigar, Coffee, Honey, Chinese and remaining workspace CI projects.
- [ ] Implement only justified conservative changes in isolated worktrees; update each project's generated task notes with old/new values, exact evidence and reproduction.
- [ ] Run each changed project's appropriate tests, fetch/rebase, commit/push without force and observe required CI/deploy state.
- [ ] Summarize per-project changes and rejected/no-change cases, with evidence and resume points.
