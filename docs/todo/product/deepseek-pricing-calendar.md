---
title: "Refresh DeepSeek holiday calendar for 2027"
status: next
area: product
due: 2026-12-15
updated: 2026-10-28
owner: agent
brief: "Verify official 2027 holidays before potential peak windows need calendar confirmation."
refs: ["docs/todo/done/product/deepseek-pricing.md"]
test: "tests/test_widget_ui.py -k deepseek"
---
- **What:** Extend `_DEEPSEEK_HOLIDAYS` in `claude_widget.py` with the verified official 2027 State Council holiday notice and recheck https://api-docs.deepseek.com/quick_start/pricing/.
- **Why:** Only2026 is currently verified; unknown-year weekday candidate peak windows deliberately show CHECK CALENDAR, while outside-window/weekend times show OFF-PEAK.
- **Next:** Locate official notice, add2027 dates and holiday/makeup-weekend boundaries in `tests/test_widget_ui.py:test_deepseek_pricing_schedule_boundaries_and_holidays`; run focused/full repository gates, push, green CI then deploy existing service. Done means2027 status verified without guessed holidays.
- **Authority/external clocks:** Routine local maintenance, published government calendar required; no provider probes/new billing/account change.
