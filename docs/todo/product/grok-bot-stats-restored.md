---
title: "Restore current Grok Bot stats and clarify their display source"
status: now
area: product
due: null
updated: 2026-11-02
owner: agent
brief: "Restore current readings via native Grok /usage and expose the reported Bot breakdown."
refs: ["docs/todo/done/product/grok-persistent-status.md"]
test: null
---
- **What:** The previous Grok snapshot reached its reset, and the local CLI access token had expired. Native `grok` followed by documented `/usage` renewed its own session without any model call. The widget's existing reader then obtained and persisted a fresh live reading including `GrokBot`.
- **Why:** An expired period must not be shown as current; the Cursor placeholder `Grok Bot — meter unavailable` also obscures the actual Grok billing breakdown.
- **Next:** Show reported Bot percentage in the collapsed Grok row, change the Cursor subline to point to that source, verify offline and in the live widget after green CI. Preserve the widget's no-token-refresh rule; native CLI alone manages its authentication.
- **Done:** Fresh live snapshot with GrokBot breakdown, visible Bot stats in the Grok row, no misleading duplicate unavailable label, tested/pushed/deployed. No model request, new account, purchase, direct token refresh or new billing.

- **Validation:** Independent review passed, including 22 Grok/Cursor tests +3 subtests. Full isolated suite passed 570 tests +46 subtests. Task tests 25 passed, generated-state/diff checks passed; isolated install verification pending. Native source restoration verified a fresh snapshot with GrokBot product and future reset. No current quota figures or credentials are committed.
