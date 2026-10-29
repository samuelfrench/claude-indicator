---
title: "DeepSeek peak/off-peak pricing in overlay"
status: done
area: product
due: null
updated: 2026-10-28
owner: agent
brief: "Shipped31e770c; green CI,531+46 tests; native PEAK label verified."
refs: []
test: "tests/test_widget_ui.py -k deepseek"
---
- **What:** Show current DeepSeek direct-API peak/off-peak pricing in collapsed and expanded overlay.
- **Why:** Existing spend and balance do not identify the current tariff.
- **Next:** Complete; annual calendar maintenance remains in docs/todo/product/deepseek-pricing-calendar.md.
- **Authority:** User-requested overlay change; no new provider test calls or billing. Normal existing service deployment follows green checks.
- **Sources checked 2026-10-28:** https://api-docs.deepseek.com/quick_start/pricing/ (Mon–Fri 01–04 and06–10UTC excluding Chinese public holidays; off-peak half peak). 2026 Chinese holiday dates: https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html . Unknown calendar years must not claim peak during potential holiday windows.
- **External clocks/upstream:** Existing CI only; no upstream contribution or external approval required.

**Implementation 2026-10-28:** `claude_widget.py:deepseek_pricing_status` uses UTC tariff windows and Beijing holiday/weekend dates, including 2026 holidays; working weekend makeup days stay off-peak. `DeepSeekUsageRow` paints PEAK (amber) or OFF-PEAK (green) beneath its heading without changing row height, in either expansion state. Local one-second timer refreshes pricing/tooltip independently of provider polling/data availability. Tooltip scopes schedule to direct API Flash/Pro and dates the official source. Unverified future-year weekday potential peak windows display CHECK CALENDAR rather than guessing.

**Focused gate:** `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_widget_ui.py -k deepseek`: 12 passed, 15 subtests; boundary seconds, weekday/weekend/makeup Saturday, holiday start/end, unknown-year fallback, timer-driven tooltip transition and collapsed/expanded render smoke. Full gates/review/deployment pending.

**Follow-up:** Before 2027, verify the official 2027 State Council holiday notice, extend `_DEEPSEEK_HOLIDAYS` in `claude_widget.py`, add holiday/makeup-weekend boundary cases to `test_deepseek_pricing_schedule_boundaries_and_holidays`, rerun focused/full gates and deploy. Until verified, CHECK CALENDAR is intentional during weekday candidate peak windows; other hours remain definitively off-peak under the checked policy.

**Full local validation:** 531 tests + 46 subtests passed; Node task tests25 passed, generated state and diff checks pass. Isolated340×30 row renders inspected for OFF-PEAK and CHECK CALENDAR: heading, label and spend fit without overlap. Final fresh installation verification/review running; native deployment pending.

**Pushed milestone:** Runtime31e770cb5ad872c2ed6e898c22f7d03e79046570; independent review passed with no findings. Final fresh install passed8 modules, inert340×753, provider HTTP/subprocesses blocked (`/tmp/indicator-deepseek-install-final.json`). Guard40806489774 succeeded; Python/install40806489681 running. Calendar follow-up now tracked separately in `docs/todo/product/deepseek-pricing-calendar.md`.

**CI retry:** Python/install40806489681 attempt1: unrelated retired Smart TODO FIFO responsiveness timing assertion0.5897s vs0.2s,530 passed+46 subtests. No changed path in that subsystem. Rerun unchanged source requested; deployment held until green.

**Retry evidence:** Exact failed FIFO test rerun locally passed1/1 in0.39s (whole pytest invocation); hosted retry still running. PEAK amber render also visually inspected at340×30.

**Accepted 2026-10-28 CT:** Exact runtime31e770cb5ad872c2ed6e898c22f7d03e79046570 pushed; guard40806489774 green and Python/install40806489681 attempt2 green (531 tests+46 subtests; fresh installed340×743,8 modules). Existing user service restarted after green CI: PID2253633 active/running,NRestarts0. Native340px overlay visually inspected at approximately02:30UTC Oct29: amber PEAK visible beneath DeepSeek, spend/credit readable; private screenshot `/tmp/indicator-deepseek-live-0.png`. Local final install340×753 and independent review also passed. No new billable service or special provider probes; existing normal polling resumed. Shared closeout note records deployment; final TODO/memory reconciliation follows.
