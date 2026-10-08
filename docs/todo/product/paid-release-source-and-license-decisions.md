---
title: "Resolve provider sources and license before a later paid release"
status: waiting-sam
area: product
due: null
updated: 2026-10-07
owner: sam
brief: "Dated terms review is complete; choose source license, supported adapters and any historical privacy cleanup before future distribution."
refs: ["docs/beta/provider-terms-check.md", "docs/beta/privacy-audit.md", "do.md"]
test: null
---
- **What:** Owner decisions identified by the completed beta audits; these are future release decisions and do not authorize a launch or changes to accounts/history.
- **Why:** Current Claude/Go/SuperGrok adapters are assessed likely prohibited absent permission; MiniMax is grey. No repository LICENSE exists, and forward cleanup leaves historical personal paths/email/operations blobs retrievable.
- **Next:** Sam chooses an explicit source license; supported-source replacements or written provider permission for Claude/Go/Grok; MiniMax hostname/paid-display interpretation; and whether historical privacy cleanup is needed. Record each decision here. Agents can later implement specifically authorized source changes with mocked tests and normal CI/service verification. No authenticated experiment, provider message, historical rewrite, force-push, paid service or launch is authorized by this entry.
- **Exact sources:** `claude_widget.py:4328` ClaudeUsageClient, `:4348` inference/header fallback, `:4393` OAuth refresh; `:1753` Go quota; `:2018` Grok CLI billing; `:1674` MiniMax quota. `docs/beta/provider-terms-check.md:49` dated assessment boundary, `docs/beta/privacy-audit.md:70` historical cleanup decision (find the current Items for Sam heading if later lines move). `do.md` gives the optional eligible Cursor Enterprise Admin key/email settings; absent key remains disconnected and is an accepted Task8 result.
- **Reproduce:** `git ls-files '*LICENSE*' '*COPYING*'` confirms0 current license files at this checkpoint; read both dated beta reports and refresh primary policies before a future paid release. The privacy audit found0 credential patterns in its bounded history screen but identified historical email/path/operations data; no urgent credential compromise was demonstrated.
- **External clocks / Sam-only:** Written provider permission may have an unknown response time and only starts when Sam authorizes contact. License selection and optional coordinated history cleanup are owner decisions. No contact has been sent; no paid service added.
- **Done:** Selected license and per-adapter supported-source/permission decisions are documented, any authorized implementation is validated/pushed/deployed, and any chosen history action has explicit scope/approval. A completed dated review does not itself clear the tool for sale. Broader user/pay/adoption milestones remain in the home sales plan.
