---
title: "Claude header data limitations and usage API compatibility"
status: next
area: product
due: null
updated: 2026-10-07
owner: agent
brief: "Keep header-only meters honest; provider terms review must precede any new authenticated probe."
refs: ["bd69af3", "TODO-archive.md#pre-task-files-2026-10-07"]
test: null
---
- **What:** Preserve missing model-scoped/extra-usage data and the unresolved token compatibility question.
- **Why:** The October 1 release reads only the rate-limit headers it receives.
- **Next:** Read `docs/beta/provider-terms-check.md` before considering a change. No provider calls are authorized by beta testing. The dated probe command below is historical, not an instruction to run it now.

- [ ] **Known limitation (not fixing):** header mode has no Fable/model-scoped meter and no extra-usage dollars — the Fable bar hides instead of showing the 08:57 value. Restoring it needs a session token (`/login` in Claude Code rewrites `.credentials.json`; the widget then prefers `/api/oauth/usage` automatically).
- [ ] **Open question:** does the setup token return 200 or 403 on `/api/oauth/usage` once its 429 window ends? 2026-04-20 it was 403; 2026-10-01 09:58 CDT it was 429 `Retry-After: 3600` (so something else drains that limit: the widget had not called it since 08:57). One probe after 10:58 CDT settles it: `curl -s -w '\n%{http_code}\n' -H "Authorization: Bearer $(cat ~/.credentials/claude-oauth-token.txt)" -H 'anthropic-beta: oauth-2025-04-20' https://api.anthropic.com/api/oauth/usage`. If 200, the client could try the usage API with the setup token first to regain the Fable bar; do not poll it repeatedly.

