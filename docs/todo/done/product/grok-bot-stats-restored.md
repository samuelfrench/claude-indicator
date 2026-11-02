---
title: "Restore current Grok Bot stats and clarify their display source"
status: done
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
- **Next:** None for this repair. Native CLI manages its own authentication; the widget does not refresh OAuth tokens. A future expired local session can be renewed through native Grok `/usage` without an inference prompt.
- **Done:** Fresh live snapshot with GrokBot breakdown, visible Bot stats in the Grok row, no misleading duplicate unavailable label, tested/pushed/deployed. No model request, new account, purchase, direct token refresh or new billing.

- **Validation:** Independent review passed, including 22 Grok/Cursor tests +3 subtests. Full isolated suite passed 570 tests +46 subtests. Task tests 25 passed, generated-state/diff checks passed; isolated fresh-install verification passed (8 installed modules, inert Qt render, provider HTTP/subprocesses blocked). Runtime commit `54eb066799300a44d204fc66abb314472bca8a7b` pushed; CI `41453100396` and guards `41453100414` passed. Native source restoration verified a fresh snapshot with GrokBot product and future reset. No current quota figures or credentials are committed.

- **Deployment:** Runtime `54eb066799300a44d204fc66abb314472bca8a7b` pushed and deployed after green CI. Existing user service restarted 2026-11-02 about 07:28 CT; PID 1784377, active/running, event-loop ready, NRestarts=0. Native capture verified the restored total and Bot percentages in the collapsed GROK row, a Cursor pointer rather than an unavailable Bot claim, and the retained Claude weekly meter with a cache-age footer. Private evidence `/tmp/claude-grok-fixed-final.png` remains untracked. Diagnostic native Grok session exited; no model calls were made.
