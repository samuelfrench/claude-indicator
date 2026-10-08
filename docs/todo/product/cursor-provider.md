---
title: "Cursor provider with separate Grok Bot line"
status: now
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Task8: sanctioned Cursor usage source or explicit disconnected state, tests and widget proof."
refs: ["do.md", "docs/beta/provider-terms-check.md", "docs/beta/privacy-audit.md"]
test: null
---
- **What:** Add Cursor alongside the existing providers, with Grok Bot shown under Cursor and separate from SuperGrok. Display included used/allowance, on-demand spend, plan and reset only when exposed by sanctioned data.
- **Why:** Grok Bot is billed through the Cursor account; conflating it with SuperGrok misstates the quota source.
- **Next:** Sole implementation agent checks official API/account scope and safely checks available configured key or local usage-display data; implement source or explicit disconnected/needs API key state, record exact setup and available fields in `do.md`, then independent review and offline full/install/CI gates plus rendered widget evidence.
- **Authority:** Explicit task8 in the authoritative goal file. Never extract/copy/print browser cookies, session tokens or passwords. No manual browser steps, invented allowance or model attribution, new Anthropic test calls, billing or account changes. Installation validation remains isolated; record actual desktop deployment separately.
- **External clocks:** Owner-supplied official API key may be needed; no key request before safe local/context checks. Missing sanctioned source is an expressly accepted shippable disconnected state, not permission to scrape authenticated endpoints.
- **Upstream:** No external contribution/publication needed.
- [ ] Determine official/local source and precise exposed fields; document account-access limitations without secrets.
- [ ] Implement Cursor and distinct Grok Bot line with explicit unavailable states.
- [ ] Focused provider/render tests, full offline suite, fresh package install, independent review and green exact-source CI.
- [ ] Record deployment/widget proof and reconcile `do.md`, generated TODO and shared memory.

**Started 2026-10-07:** Original beta CI succeeded at5d5616d; task8 is new runtime scope. Root keeps beta completion records; the implementation agent exclusively owns Cursor code and this task.
