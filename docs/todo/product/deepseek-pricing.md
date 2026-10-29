---
title: "DeepSeek peak/off-peak pricing in overlay"
status: now
area: product
due: null
updated: 2026-10-28
owner: agent
brief: "Implement direct-API pricing schedule label with offline clock refresh."
refs: []
test: "tests/test_widget_ui.py -k deepseek"
---
- **What:** Show current DeepSeek direct-API peak/off-peak pricing in collapsed and expanded overlay.
- **Why:** Existing spend and balance do not identify the current tariff.
- **Next:** Independent review and final fresh installation gate, commit/push, green CI then normal service deployment and runtime evidence.
- **Authority:** User-requested overlay change; no new provider test calls or billing. Normal existing service deployment follows green checks.
- **Sources checked 2026-10-28:** https://api-docs.deepseek.com/quick_start/pricing/ (Mon–Fri 01–04 and06–10UTC excluding Chinese public holidays; off-peak half peak). 2026 Chinese holiday dates: https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html . Unknown calendar years must not claim peak during potential holiday windows.
- **External clocks/upstream:** Existing CI only; no upstream contribution or external approval required.

**Implementation 2026-10-28:** `claude_widget.py:deepseek_pricing_status` uses UTC tariff windows and Beijing holiday/weekend dates, including 2026 holidays; working weekend makeup days stay off-peak. `DeepSeekUsageRow` paints PEAK (amber) or OFF-PEAK (green) beneath its heading without changing row height, in either expansion state. Local one-second timer refreshes pricing/tooltip independently of provider polling/data availability. Tooltip scopes schedule to direct API Flash/Pro and dates the official source. Unverified future-year weekday potential peak windows display CHECK CALENDAR rather than guessing.

**Focused gate:** `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_widget_ui.py -k deepseek`: 12 passed, 15 subtests; boundary seconds, weekday/weekend/makeup Saturday, holiday start/end, unknown-year fallback, timer-driven tooltip transition and collapsed/expanded render smoke. Full gates/review/deployment pending.

**Follow-up:** Before 2027, verify the official 2027 State Council holiday notice, extend `_DEEPSEEK_HOLIDAYS` in `claude_widget.py`, add holiday/makeup-weekend boundary cases to `test_deepseek_pricing_schedule_boundaries_and_holidays`, rerun focused/full gates and deploy. Until verified, CHECK CALENDAR is intentional during weekday candidate peak windows; other hours remain definitively off-peak under the checked policy.

**Full local validation:** 531 tests + 46 subtests passed; Node task tests25 passed, generated state and diff checks pass. Isolated340×30 row renders inspected for OFF-PEAK and CHECK CALENDAR: heading, label and spend fit without overlap. Final fresh installation verification/review running; native deployment pending.
