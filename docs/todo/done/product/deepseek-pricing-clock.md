---
title: "DeepSeek pricing windows and current clock"
status: done
area: product
due: null
updated: 2026-10-28
owner: agent
brief: "Shipped9bc1de8; UTC windows/live seconds visible and native verified."
refs: ["docs/todo/done/product/deepseek-pricing.md"]
test: "tests/test_widget_ui.py -k deepseek"
---
- **What:** Show peak windows and current UTC time visibly in the collapsed and expanded DeepSeek overlay; clock updates with existing local timer.
- **Why:** User needs to compare now with the pricing windows directly.
- **Next:** Complete; related annual holiday refresh stays in docs/todo/product/deepseek-pricing-calendar.md.
- **Authority/external clocks:** User-requested local feature and existing deployment path; hosted CI only. No new billing, provider probes or account changes; no reusable upstream lane.

**Implementation/validation:** DeepSeek row now60px collapsed/118px expanded, +30px for visible peak01:00–04:00 /06:00–10:00UTC, weekday/holiday caption, and NOW HH:MM:SS UTC. Clock/status share one timestamp per existing1s local timer. Focused14 tests+15 subtests and full531+46 passed; Node25, build/diff checks pass. Isolated340px render visually inspected; install and independent review pending, then CI/deployment.

**Pushed:** Runtime9bc1de8bf3e8ea0a99b46eacdd1dbfe0729cce44. Independent review passed without findings. Fresh8-module isolated installation and inert340×783 render passed (`/tmp/indicator-clock-install.json`), no service/autostart changes. Guard40807082991 green, Python/install40807082965 running. Deploy after exact-source green; native inspect live clock advancing and windows visible.

**Accepted 2026-10-28 CT:** Runtime9bc1de8bf3e8ea0a99b46eacdd1dbfe0729cce44 pushed. Hosted guard40807082991 and Python/install40807082965 green (531 tests+46 subtests, fresh8-module340×773 installed render). Restarted existing service after green CI: PID2264933 active/running,NRestarts0. Native screenshot `/tmp/indicator-clock-live.png` inspected: PEAK, both UTC windows, Mon–Fri/holiday caption and NOW02:35:10UTC all visible; second capture `/tmp/indicator-clock-live-2.png` shows02:35:17UTC proving clock advancement. No new billing/special provider probes; ordinary polling resumed. Independent review and local full/install gates passed.
