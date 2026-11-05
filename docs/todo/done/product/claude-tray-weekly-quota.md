---
title: "Claude tray icon shows the 7-day meter when there is no 5-hour limit"
status: done
area: product
due: null
updated: 2026-11-05
owner: agent
brief: "Tray C showed ? permanently on Ultra (weekly-only quota); now shows 7-day percent marked CW."
refs: ["claude_widget.py", "tests/test_widget_ui.py", "README.md", "docs/todo/done/product/claude-usage-history-recording.md"]
test: null
---
- **What:** The tray **C** icon read only the five-hour window. Verified Ultra accounts have no five-hour limit (Anthropic notice 2026-10-30/31), so the local status-line feed carries only `seven_day` and C showed `?` with `Claude 5-hour usage: unavailable — 5-hour reset time unknown` on every refresh since 2026-11-01.
- **Fix:** `ClaudeWidget._claude_tray_quota` selects the 7-day entry whenever `history_series_for(data)` returns the 7-day series (status-line source, no five-hour reset, a seven-day reset), the same rule the history graph uses. The state carries `window_mark="W"`; `build_quota_tray_icon(..., window_mark)` paints `C` plus a smaller `W` (shifted left so the amber cached dot stays clear at 24 px); the tooltip reads `Claude 7-day usage: N% used`, the reset countdown and `W: weekly limit (no 5-hour limit reported)`. Expiry, reset and cached rules are unchanged and apply to the weekly window. When the five-hour window exists, C shows it unmarked as before. An API/header snapshot without a five-hour reset still shows unavailable; only the local feed signals an absent limit. `_update_tray_quotas` keys the icon cache on `(used, cached, mark)`. README tray paragraph updated.
- **Validation:** New `test_claude_tray_shows_weekly_meter_marked_w_when_no_five_hour_limit` (weekly value, mark, tooltip, weekly reset -> unavailable, five-hour present -> unmarked 5-hour) fails on `origin/master` with `AssertionError: None != 38`; `test_claude_tray_keeps_five_hour_label_when_api_reports_no_window`; icon test adds three CW cases (all images distinct at 16/22/24/32/64 px). Isolated-HOME full suite (CI env): `585 passed, 49 subtests passed`; `scripts/verify_install.py` exit 0 (fresh venv, isolated home, no service changes); task tests and `build.mjs --check` pass; `git diff --check` clean.
- **Next:** None.
