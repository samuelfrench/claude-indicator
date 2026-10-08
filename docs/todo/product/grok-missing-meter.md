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
- **What:** A billing response can contain a weekly period but omit `creditUsagePercent`, while `onDemandCap.val` is zero.
- **Why:** `parse_grok_credits` reports `Grok billing has no weekly or on-demand meter`; silently treating an absent field as zero would conceal unknown usage.
- **Next:** Run `python3 -m pytest -q tests/test_widget_ui.py -k 'grok or parse_grok'` with isolated state and the test HTTP guard. `tests/test_widget_ui.py` covers the missing-meter schema with a fixture. Await a documented provider schema before changing absent-field interpretation; no live request is needed.
- **Deferred fix:** Add an explicitly supported absent-field interpretation if provider documentation establishes one. Until then the visible unavailable/error state is intentional and unchanged.
