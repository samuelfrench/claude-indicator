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
- **Next:** Sole implementer finishes migration; root owns provider/privacy/recruit evidence; then build and validate packaging/forms without touching the owner widget.
- **Authority:** Four original requirements plus added recruiting/tracking requirements 5–6. No public release, README GIF, Pro tier, HN/Reddit/X launch, replies/DMs/likes/follows, email, money, new Anthropic API test calls, other projects or tmux sessions. Use mocks and isolated installation validation; do not restart the owner's running indicator.
- **External clocks:** Terms and public community rules require current read-only evidence. Any later posting needs explicit owner approval; drafts do not start a posting clock. No new billing or account enrollment is needed.
- **Upstream targets:** No upstream patch/listing is needed for this beta scope; external publication remains held.

- [ ] Enumerate every provider/data source, read current public terms and usage policies, classify allowed/grey area/likely prohibited with relevant clause URLs and safer-source guidance in `docs/beta/provider-terms-check.md`; avoid legal certainty.
- [ ] Audit all network calls/data flows, telemetry, credential claim and accurate headline; audit current public files and Git history, safely fix current exposure without rewriting history; record owner-only history/repository decisions in `docs/beta/privacy-audit.md`.
- [ ] Provide one-command beta installation, honest supported-platform requirements, clean fresh-environment proof and sensible tests without touching the running widget.
- [ ] Add `.github/ISSUE_TEMPLATE/beta-signup.yml`, `beta-feedback.yml`, and a short README Beta section with install command and form links; no GIF or launch copy.
- [ ] Find 25–30 recent (roughly 14-day) X/Reddit usage-limit/reset complaints; check community self-promotion rules, skip forbidding communities, and save ranked truthful varied 1–3 sentence replies disclosing “I built”, repo link and provider question to the owner's local recruitment Markdown and CSV. Do not post.
- [ ] Maintain local recruits tracker with one row per actual signup, source/date/provider requests and running provider tally; check signup/feedback issues each work session.
- [ ] Run actual gates, commit/push tested work with green CI, record that live-widget deployment is explicitly held, and reconcile project TODO, owner plan and shared memory before final report.

**Started 2026-10-07:** Primary `master` and `origin/master` matched `d857694a050ddfb8774ce99be64e774ded5d9426` before work; tree was clean and no GitHub workflow existed. TODO migration is the first implementation lane. Recruitment and tracker records remain local, with no send/post action authorized.

