---
title: "DeepSeek pricing windows and current clock"
status: now
area: product
due: null
updated: 2026-10-28
owner: agent
brief: "Add visible UTC windows and live current time beside pricing status."
refs: ["docs/todo/done/product/deepseek-pricing.md"]
test: "tests/test_widget_ui.py -k deepseek"
---
- **What:** Show peak windows and current UTC time visibly in the collapsed and expanded DeepSeek overlay; clock updates with existing local timer.
- **Why:** User needs to compare now with the pricing windows directly.
- **Next:** Targeted implementation/tests, independent review, full repository gates and fresh install, commit/push, green CI, normal service deployment and native inspection; reconcile TODO/memory.
- **Authority/external clocks:** User-requested local feature and existing deployment path; hosted CI only. No new billing, provider probes or account changes; no reusable upstream lane.

**Implementation/validation:** DeepSeek row now60px collapsed/118px expanded, +30px for visible peak01:00–04:00 /06:00–10:00UTC, weekday/holiday caption, and NOW HH:MM:SS UTC. Clock/status share one timestamp per existing1s local timer. Focused14 tests+15 subtests and full531+46 passed; Node25, build/diff checks pass. Isolated340px render visually inspected; install and independent review pending, then CI/deployment.
