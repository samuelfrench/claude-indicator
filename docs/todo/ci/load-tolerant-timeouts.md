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
- **Next:** Read-only inventory complete in `~/indicator-beta/task7-timeout-inventory.md`; sole Task7 implementer now executes BBQ then Coffee in distinct worktrees, runs focused/full gates and prepares per-project commits for root review/push/CI. Cursor implementation/review has finished; primary checkout edits stay preserved.
- **Authority:** Explicit task7 expands the original other-project restriction solely for timeout/retry changes. Roughly1.5–2× proven waits or at most1–2 known-flaky retries; retain assertions/checks. Never weaken Cigar production deployment verification, build the BBQ-owned machine-wide lock, touch other sessions, force-push, skip tests or alter runtime behavior.
- **External clocks:** Green existing CI and any deploy path depend on each project's current state; record exact code/live identities where applicable. No new services/billing.
- **Upstream:** No dependency patch or publication needed unless inventory proves a reusable third-party defect.
- [x] Inventory recent failures/current fixes and active files for BBQ, Cigar, Coffee, Honey, Chinese and remaining workspace CI projects.
- [ ] Implement only justified conservative changes in isolated worktrees; update each project's generated task notes with old/new values, exact evidence and reproduction.
- [ ] Run each changed project's appropriate tests, fetch/rebase, commit/push without force and observe required CI/deploy state.
- [ ] Summarize per-project changes and rejected/no-change cases, with evidence and resume points.

**2026-10-07 evidence milestone:** Reviewer found39 primary workspace repos with CI test/build/verification workflows;37 Sam-owned refs fetched,2 upstream checkouts excluded. Root independently read BBQ failed CI logs: run37708532468 failed exactly CompareTray composition at15,000ms (498/499 tests); run37709190412 failed exactly MeatGuide accessibility at120,000ms (498/499). Current origin values are unchanged. Candidate patch is30,000ms only for the composition case and180,000ms only for the full-rule axe case, with no retries/assertion changes. Commit001fee3 records load24.6–35.1 on32cores and other-repo runner contention; isolated Compare7/7in5.7s and subsequent green001fee3 deploy are supporting evidence. Cigar latest failure is an assertion mismatch rather than load timeout; production verification remains excluded. Wait for the sole Cursor implementer to finish, then make BBQ changes in a new worktree. Full per-project inventory remains pending.

**2026-10-07 inventory/implementation milestone:**37 owned CI repos fetched/screened,39 including2 excluded upstream checkouts. Only BBQ and Coffee qualify. Coffee committed setup sets asyncUtilTimeout5,000ms (not library default1,000); two repeated status waits get10,000ms and one actual30,000ms CityGuide reload/hash case gets45,000ms. Assertions stay unchanged; no retries/global waits. Cigar/Honey/Chinese and other32 repositories receive no patch: assertion/network causes, existing readiness fixes or no load proof. Exact receipts/rejected causes are private in the inventory. Worktrees `indicator-task7-bbq-20261008-031246-08bc1` at38b48cde and `indicator-task7-coffee-20261008-031246-08bc1` at64e13954 under the workspace .worktrees directory. BBQ focused2files/8tests passed (Compare9.86s; full-ruleaxe77.30s; total81.02s) underload29.20; full suite/typecheck/build and guards are running. Nothing has yet been pushed in those projects.

**2026-10-07 BBQ local gate:** Candidate `360ea83d450a29e5bc87af4ec62b87cce73da9f8` is rebased on fetched origin `3fc8df52ec94fb1dbf1a49e30076b3854f7b6b94`, clean and held for independent review before push. Exactly two timeout literals changed; assertions and runtime code are byte-unchanged. Full frontend passed68files/499tests in212.92s, focused8/8, typecheck/build and offline gates passed; TODO31/drift passed. Initial missing-type dependency failure is preserved, clean npm ci restored only missing @types/node/undici-types, all other package versions and14 runtime/test package hashes matched. Coffee is now the sole implementation lane, rebased on38bbef3; focused/full gates are underway for its three narrowly evidenced waits. Private logs: `~/indicator-beta/task7-logs/`; summary: `~/indicator-beta/task7-implementation.md`.
