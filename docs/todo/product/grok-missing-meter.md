---
title: "Grok billing response can omit a usage meter"
status: known-failure
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Missing meter remains a visible error; do not guess zero from an absent field."
refs: ["tests/test_widget_ui.py", "TODO-archive.md#pre-task-files-2026-10-07"]
test: "tests/test_widget_ui.py Grok billing has no weekly or on-demand meter"
---
- **What:** Historical Grok payload shape can omit a valid usage meter.
- **Why:** Reporting zero would conceal unknown usage.
- **Next:** Use existing mock response tests; await a documented provider schema before changing absent-meter behavior. No live request is required.

- Live SuperGrok billing 200 omits `creditUsagePercent` and has `onDemandCap.val=0` while still sending a weekly `currentPeriod` (probed 2026-09-09, HTTP 200, 413-byte JSON, `isUnifiedBillingUser: true`). `parse_grok_credits` raises `Grok billing has no weekly or on-demand meter`; that payload is still a visible error, not 0%; `tests/test_widget_ui.py` covers it. Real fix not done: treat proto3-omitted `creditUsagePercent` as 0% for unified weekly users — the plan forbids guessing 0%. **2026-09-17:** this is not why the GROK row was empty during OpenCode Grok use. Grok CLI `expires_at` is `2026-09-17T03:41:19Z` (expired). OpenCode `xai` oauth against the same endpoint returns `creditUsagePercent: 27` / `GrokBuild` 27% (HTTP 200, 500 bytes). Parser unchanged.

