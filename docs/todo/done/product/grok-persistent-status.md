---
title: "Grok usage stays visible after the CLI token expires"
status: done
area: product
due: null
updated: 2026-10-30
owner: agent
brief: "Persist the last live Grok reading and show GROK CACHE until reset instead of a blank dash between CLI logins."
refs: ["claude_widget.py", "README.md", "docs/beta/privacy-audit.md", "docs/todo/product/grok-missing-meter.md"]
test: "tests/test_widget_ui.py -k grok"
---
- **What:** The Grok row showed `—` whenever the short-lived Grok CLI access token expired, which happens hours after the CLI is last used. Sam saw this as Grok being disconnected until he started using it. Persist each successful reading to a mode-0600 local snapshot and render it as `GROK CACHE` with its read time until the reported reset (or 24 hours when the response has no reset).
- **Why:** The widget already polls every five minutes and must not rotate Grok OAuth tokens. A local last-reading snapshot keeps the weekly/on-demand meter visible without inventing a value, refreshing credentials or adding a provider call.
- **Next:** Complete. The separate Cursor row still shows its documented `Not connected · needs API key` state until an eligible Cursor Enterprise Admin key is supplied; that row is not a Grok status.
- **Authority/external clocks:** User-requested local display change and the existing user-service deployment path. No new billing, provider endpoint, token refresh, account action or upstream contribution. Snapshot contains usage fields only, no credentials or account identity.

**Implementation/validation:** `GROK_SNAPSHOT_PATH` defaults to `~/.claude/grok_usage_snapshot.json`; `save_grok_snapshot` uses a mode-0600 atomic replace, `load_grok_snapshot` rejects non-owner/non-0600/symlink files, future or corrupt timestamps, expired resets and readings older than `GROK_SNAPSHOT_MAX_AGE_S` (24h) when no reset is reported. `read_grok_usage` writes on success and falls back to the snapshot on auth/fetch failure, retaining the live error in the tooltip. The row seeds from the snapshot at construction, marks the title `GROK CACHE`, and shows the last successful read time. Full offline suite passed 553 tests + 46 subtests; focused Grok/Cursor selection passed 21 tests + 3 subtests; fresh isolated install/render passed (8 modules, 340×783, provider HTTP and subprocesses blocked), Node task tests 25/25 and `build.mjs --check` passed.
