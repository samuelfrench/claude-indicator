---
title: "Claude Indicator beta phase 1"
status: now
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Terms/privacy audit, clean one-command install, issue forms and draft recruiting; no public launch or posting."
refs: ["docs/beta/provider-terms-check.md", "docs/beta/privacy-audit.md"]
test: null
---
- **What:** Complete the authoritative beta plan and its October 7 additions.
- **Why:** Public distribution and later paid use need provider-policy, privacy and installation evidence first.
- **Next:** Migration committed as `130efb9`; sole implementer now finishes packaging/forms and forward-only privacy cleanup. Root completes audit evidence and `~/indicator-beta/recruit-candidates.{md,csv}` / `recruits.md`; then run clean install/full CI and requirement audit.
- **Authority:** Four original requirements plus added recruiting/tracking requirements 5–6. No public release, README GIF, Pro tier, HN/Reddit/X launch, replies/DMs/likes/follows, email, money, new Anthropic API test calls, other projects or tmux sessions. Use mocks and isolated installation validation; do not restart the owner's running indicator.
- **External clocks:** Terms and public community rules require current read-only evidence. Any later posting needs explicit owner approval; drafts do not start a posting clock. No new billing or account enrollment is needed.
- **Upstream targets:** No upstream patch/listing is needed for this beta scope; external publication remains held.

- [x] Enumerate every provider/data source, read current public terms and usage policies, classify allowed/grey area/likely prohibited with relevant clause URLs and safer-source guidance in `docs/beta/provider-terms-check.md`; avoid legal certainty.
- [x] Audit all network calls/data flows, telemetry, credential claim and accurate headline; audit current public files and Git history, safely fix current exposure without rewriting history; record owner-only history/repository decisions in `docs/beta/privacy-audit.md`.
- [ ] Provide one-command beta installation, honest supported-platform requirements, clean fresh-environment proof and sensible tests without touching the running widget.
- [x] Add `.github/ISSUE_TEMPLATE/beta-signup.yml`, `beta-feedback.yml`, and a short README Beta section with install command and form links; no GIF or launch copy.
- [ ] Find 25–30 recent (roughly 14-day) X/Reddit usage-limit/reset complaints; check community self-promotion rules, skip forbidding communities, and save ranked truthful varied 1–3 sentence replies disclosing “I built”, repo link and provider question to the owner's local recruitment Markdown and CSV. Do not post.
- [ ] Maintain local recruits tracker with one row per actual signup, source/date/provider requests and running provider tally; check signup/feedback issues each work session.
- [ ] Run actual gates, commit/push tested work with green CI, record that live-widget deployment is explicitly held, and reconcile project TODO, owner plan and shared memory before final report.

**Started 2026-10-07:** Primary `master` and `origin/master` matched `d857694a050ddfb8774ce99be64e774ded5d9426` before work; tree was clean and no GitHub workflow existed. TODO migration is the first implementation lane. Recruitment and tracker records remain local, with no send/post action authorized.


**2026-10-07 checkpoint:** Generated TODO migration verified 0 missing lines (53 nonempty original lines), all 4 open checkboxes preserved; 25 Node tests passed and 8-task drift check passed, local commit `130efb9be433a7895f9c25c47b1fdad14ae7d473`. Root fetched origin and screened 150 reachable commits / 359 blobs / 19,912,070 bytes; 0 credential-pattern matches, but personal host/operational data requires safe current-tree cleanup plus Sam history decision. `docs/beta/privacy-audit.md` records all network/local flows and headline qualification. Read-only GitHub issue check returned 0 issues; private recruits tracker has 0 confirmed signups and no provider requests. Running service PID 116278 since 2026-10-06 remains untouched. The goal file appended recruiting requirements and then conflicting posting permission while the thread still says no posting; private research/drafts continue pending direct clarification. No external clocks were started.

**2026-10-07 audit milestone:** Provider report and independent privacy review completed. Current adapters: Claude/Go/Grok likely prohibited, MiniMax grey area, Codex/DeepSeek/local Ollama/local ComfyUI/authorized GitHub reads allowed with conditions; no AWS runtime flow. Official Claude statusline quota fields provide a safer local alternative for a later adapter change. All 11 requests + 2 urllib call sites, 3 gh commands, Codex delegation/browser/local socket are covered. Current-tree screen reports 0 owner paths/personal emails/private-project defaults/account-number-like matches after forward-only cleanup; historical exposure remains a Sam decision. Focused packaging/privacy test gate: 217 passed +9 subtests. Clean install and full CI proof remain in progress.

**2026-10-07 implementation gate:** Sole implementer finished package/CLI/forms, offline test guard, fresh-install verifier and CI. Full isolated suite passed **462 tests +14 subtests in 7.43s**; focused 217 +9 subtests; Node25; YAML parse, compile, diff and TODO drift checks passed. Fresh local venv (Python3.13.9/PySide6 6.11.2) imported all 7 installed modules outside checkout, passed help/version and rendered the inert Qt widget340×705 with HTTP/subprocess creation blocked. Details: `docs/beta/install-validation.md`; private receipt: `~/indicator-beta/install-local-evidence.json`. Independent code review is underway; remote pipx install and green pushed CI remain required. Deployment means making the tested source/forms available on master; the existing desktop widget is explicitly not restarted or reconfigured.
