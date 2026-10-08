---
title: "Cursor provider with separate Grok Bot line"
status: now
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Task8: sanctioned Cursor usage source or explicit disconnected state, tests and widget proof."
refs: ["do.md", "docs/beta/provider-terms-check.md", "docs/beta/privacy-audit.md"]
test: "tests/test_cursor_usage.py; tests/test_widget_ui.py"
---
- **What:** Add Cursor alongside the existing providers, with Grok Bot shown under Cursor and separate from SuperGrok. Display included used/allowance, on-demand spend, plan and reset only when exposed by sanctioned data.
- **Why:** Grok Bot is billed through the Cursor account; conflating it with SuperGrok misstates the quota source.
- **Next:** Independent review of the Cursor commit, exact-source hosted Python/install and repository guards, then root records any authorized desktop deployment/display proof. Current shipped source state is disconnected because no eligible key is configured; setup and field limits are in `do.md`.
- **Authority:** Explicit task8 in the authoritative goal file. Never extract/copy/print browser cookies, session tokens or passwords. No manual browser steps, invented allowance or model attribution, new Anthropic test calls, billing or account changes. Installation validation remains isolated; record actual desktop deployment separately.
- **External clocks:** Owner-supplied official API key may be needed; no key request before safe local/context checks. Missing sanctioned source is an expressly accepted shippable disconnected state, not permission to scrape authenticated endpoints.
- **Upstream:** No external contribution/publication needed.
- [x] Determine official/local source and precise exposed fields; document account-access limitations without secrets.
- [x] Implement Cursor and distinct Grok Bot line with explicit unavailable states.
- [ ] Focused provider/render tests, full offline suite, fresh package install, independent review and green exact-source CI.
- [ ] Record deployment/widget proof and reconcile `do.md`, generated TODO and shared memory.

**Started 2026-10-07:** Original beta CI succeeded at5d5616d; task8 is new runtime scope. Root keeps beta completion records; the implementation agent exclusively owns Cursor code and this task.

**Source milestone 2026-10-07:** Current official Admin API is listed for Enterprise teams and supports team-scoped Basic authentication and `POST https://api.cursor.com/teams/spend` filtered by `searchTerm`; exact target email is checked before using a member. `spendCents` is on-demand, `overallSpendCents` includes included usage, and `subscriptionCycleStart` is cycle start only. Plan, included allowance, reset date and Grok Bot-specific usage are not exposed by this endpoint. Current documented official keys use `crsr_` with `admin:*`; unsupported key prefixes are rejected. Environment/candidate-file presence checks found no configured official key or target email, and the standard Cursor local usage database is absent. No session/cookie/password data was inspected or provider request made. Implementing the explicitly permitted disconnected state plus an official-key connection path; no personal-plan Admin access or Bot attribution is inferred.

**Implementation milestone 2026-10-07:** Added `cursor_usage.py` with one fixed, filtered `POST /teams/spend`, exact member selection, sanitized errors and a protected key-file fallback; added a separate Cursor row with a permanently distinct Grok Bot subline, hide/unhide, hourly polling and bounded shutdown participation. Focused offline gate passed **50 tests + 3 subtests** (`tests/test_cursor_usage.py` and affected widget checks), with requests/CLI blocked and isolated HOME. No Cursor CLI is on PATH (`agent` resolves to Grok); official CLI `/usage` exists but no published local cache schema was found. Installed Grok Bot display source keeps usage in memory; its getters make private authenticated RPC calls and were not invoked. No disk usage snapshot was identified, so neither private RPC nor browser/session extraction is used. Full suite, clean install/render and independent review remain pending.

**Local verification milestone 2026-10-07:** Final focused gate passed **57 tests + 3 subtests**, full isolated offline suite passed **517 tests + 20 subtests in 7.51s**, and Node task tests passed **25 tests**. Clean venv installation proved all **8 modules** from installed site-packages, help/version and the actual inert widget at **340×753** (Python3.13.9/PySide6 6.11.2), with HTTP and subprocess creation blocked; the inspected image visibly shows Cursor disconnected and Grok Bot separately. Initial full gate found two inherited 860px expanded-panel assertions: the new row contributes exactly **44px + 4px layout spacing**. Revised checks preserve the old 860px budget with Cursor hidden, require the exact added height, and retain screen/clamp/value assertions. Numeric extremes are sanitized and unsupported key prefixes rejected. Issue-form/workflow YAML parses and diff checks pass. Private evidence: `~/indicator-beta/test-cursor-{focused,full}-final.log`, `~/indicator-beta/install-cursor-local-evidence.json`, `~/indicator-beta/cursor-inert-widget.png`. Independent review, hosted gates and desktop deployment remain pending; no provider request or live service change occurred.
