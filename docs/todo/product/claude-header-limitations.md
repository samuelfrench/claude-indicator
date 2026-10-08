---
title: "Claude header data limitations and usage API compatibility"
status: next
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Keep header-only meters honest; provider terms review must precede any new authenticated probe."
refs: ["bd69af3", "TODO-archive.md#pre-task-files-2026-10-07"]
test: null
---
- **What:** Preserve missing model-scoped/extra-usage data and the unresolved setup-token compatibility question.
- **Why:** Header-sourced quotas provide only the supplied five-hour/seven-day meters; unsupported fields must not show stale values.
- **Next:** Read `docs/beta/provider-terms-check.md` before considering a change. Use `python3 -m pytest -q tests/test_widget_ui.py -k 'unified_ratelimit or probe or oauth_token'` with isolated user state and the test HTTP guard. No authenticated probe is authorized by beta testing.

- [ ] **Known limitation (deferred):** Header mode has no model-scoped meter or extra-usage dollars. Those fields stay hidden unless a current usage-endpoint response supplies them.
- [ ] **Compatibility question (deferred):** Whether a long-lived setup token may use the usage endpoint remains unverified. A documented provider-supported source and terms permission must precede any authenticated experiment. Beta tests use mocked responses only.
