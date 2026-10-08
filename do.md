# Cursor connection and available data

Task 8 source check, 2026-10-07: no explicitly configured official Cursor Admin key or target email was found. Neither `cursor` nor `cursor-agent` is on PATH; the installed command named `agent` resolves to the Grok CLI. The standard Cursor local data directory checked was absent. Static inspection of the installed Grok Bot desktop's usage-display implementation identified in-memory usage values, but no stored usage snapshot in that installed version. Its IPC getters perform private authenticated provider calls, so they were not invoked. Browser cookies, client session tokens, passwords and account authentication databases were not read. No provider request was made during implementation or testing.

The widget therefore ships a visible **Cursor: Not connected · needs API key** row and a distinct **Grok Bot: meter unavailable** subline. It does not show unknown values as zero and does not treat SuperGrok credit as Cursor usage. Installation and this source check did not change the running desktop widget or its service; isolated render proof is recorded in the task and install-validation document.

## Exact settings

For an account eligible for the [official Enterprise Admin API](https://cursor.com/docs/api), supply an owner-authorized **Cursor Enterprise team Admin API key with `admin:*` scope** as `CURSOR_ADMIN_API_KEY` in the widget process environment. Current documented keys use the `crsr_` prefix. Set `CURSOR_ACCOUNT_EMAIL` to the exact member email whose spending should be displayed. The email is used only as the official API's search filter and for exact response matching; it is not displayed or saved by the Indicator. No key creation, account change or manual browser action is performed by this implementation.

Alternatively, place the key alone in `$XDG_CONFIG_HOME/claude-indicator/cursor-admin-api-key.txt`, defaulting to `~/.config/claude-indicator/cursor-admin-api-key.txt`. Use an owner-controlled regular file with mode `0600` and a private directory, not a symlink. Environment key takes precedence. `CURSOR_ACCOUNT_EMAIL` remains required. Do not put the key or account email into the repository, public issue, screenshot or command history. The reader ignores missing/unsafe key files and reports a configuration state without making a request.

Personal Cursor Pro/Pro+/Ultra access is not a promise of Enterprise Admin API eligibility. Cloud Agents, Origin, Grok/xAI API keys and browser/session credentials are different products and are not accepted as substitutes. If no eligible key is supplied, leave this row disconnected; the task explicitly permits that shipped state. The [official CLI release notes](https://cursor.com/docs/release-notes) describe `/usage` with plan meters and resets, but do not establish a documented persisted usage cache for this adapter. No undocumented usage HTTP endpoint or token extraction is substituted.

## Displayed fields and limits

The reader makes one hourly `POST https://api.cursor.com/teams/spend` using HTTP Basic authentication (key as username, empty password), `searchTerm` set to the configured email, page 1 and page size 100. It disables redirects, requires exactly one case-insensitive exact email match, and discards unrelated returned members. It does not enumerate all team members, follow broad pagination or make inference requests. Missing/ambiguous matches, unauthorized access, malformed data and errors show unavailable values without exposing response bodies or credentials.

| Field | Current official spending schema / Indicator behavior |
| --- | --- |
| Included usage used | `(overallSpendCents - spendCents) / 100` dollars, only when both amounts are valid and total is at least on-demand spend |
| On-demand used/spend | `spendCents / 100` dollars for the current billing cycle |
| Included allowance | Not exposed; displayed as unavailable |
| Plan name | Not exposed; displayed as unavailable |
| Billing-cycle reset/end | Not exposed; displayed as unavailable |
| Billing-cycle start | `subscriptionCycleStart` in milliseconds, labelled **cycle start** in UTC; never used to invent a reset date |
| Spending caps | `monthlyLimitDollars`, `hardLimitOverrideDollars` and `effectivePerUserLimitDollars` are budgets, not included allowances; this adapter does not turn them into quota |
| Grok Bot | Distinct Cursor subline; `/teams/spend` does not expose a Bot-specific meter. Grok-model use is not evidence of Grok Bot attribution |

These are current-cycle monetary usage figures, not request/token counts or a personal-plan invoice. Cursor's organization pooled usage API reports organization-wide contract data; it is not used as an individual allowance/reset. No guessed monthly reset, fixed plan allowance or overlapping grant is displayed. [Grok Bot billing](https://cursor.com/help/grok-bot/plans) uses Cursor billing and is separate from SuperGrok; a linked plan's included grant is not a second meter to add. [Admin API spending documentation](https://cursor.com/docs/account/teams/admin-api) is the schema source.

## Verified deployment

`b8d72851dd44cf8af0f637b70cf656dc0723f0b1` is pushed with green hosted517 tests+20 subtests and fresh8-module install/render. Task8 was deployed through the existing user service on2026-10-07 at22:16:25 CT; root verified the actual X11 widget’s Cursor and separate Grok Bot lines. The runtime is disconnected because no eligible key or stored snapshot is available. This production update happened after isolated installation validation finished; installation itself never starts or changes services. No new services or paid API testing were introduced.


## Recheck 2026-10-08 01:56 CT

Task 8’s sanctioned-source rules were reread. Configuration-name and file-metadata checks again found no Cursor Admin key or target account email configured for the widget, and no standard local usage database. Current [API overview](https://cursor.com/docs/api), [spending schema](https://cursor.com/docs/account/teams/admin-api) and [Grok Bot billing](https://cursor.com/help/grok-bot/plans) still support the source and display distinctions documented above. Exact settings remain `CURSOR_ADMIN_API_KEY` with an eligible Enterprise Admin `crsr_` key scoped `admin:*`, plus `CURSOR_ACCOUNT_EMAIL`; no browser/session credential is a substitute. No account action or authenticated usage request was made.

The shipped application bytes remain unchanged. Fresh isolated provider/widget tests passed 196 tests plus 13 subtests; a fresh inert render visibly retained Cursor’s disconnected row and the separate Grok Bot unavailable line. The existing deployed service remains active with zero restarts. No service restart or new deployment was needed for this verification. The allowed fallback remains the shipped result until an eligible sanctioned source is supplied.


## Promotion-channel research — October 8, 2026

Sam’s 09:08 AM CT job is research only: no posting, commenting, submissions, sign-ups or emails anywhere, and no other Indicator work today. This holds the earlier bounded Reddit/X reply authority for today. No runtime/package change, provider request, deployment, account action or spend was made.

The private report is `~/indicator-beta/promo-channels-2026-10-08.md`. It ranks four alternatives: (1) Console.dev’s explicitly invited developer-beta suggestion, (2) Latent.Space’s editorial AI-coding-tool pitch, (3) Show HN if Sam’s existing account is eligible and he personally writes/posts/discusses, and (4) Future Tools’ manually reviewed submission form. Ranking reflects fit/rules/effort, not measured acquisition or guaranteed acceptance. Future emails, submissions and public launches need their own later authority; nothing is queued.

The report checks current primary submission/rules URLs and manual/account requirements, compares Changelog, DEV, Product Hunt, Lobsters, Indie Hackers, TLDR AI and Discords, and assesses four US writer/creator prospects privately. HN forbids generated text and automated posting and currently restricts Show HN access without publishing a numeric cutoff. DEV’s AI policy excludes AI-assisted promotional articles. Product Hunt requires a personal account at least one week old. Lobsters needs invitation and restricts new users for70days. Future Tools’ form includes CAPTCHA; its business inbox is not the tool-submission route. Changelog excludes commercial pitches, and the Indicator’s license remains an existing owner decision.

Rules for r/ClaudeAI, r/ChatGPTCoding, r/cursor, r/LocalLLaMA and r/SideProject could not be verified: all five public JSON reads returned403, public rule pages lacked usable rule text, and the isolated SideProject page hit a humanity challenge. No challenge action or workaround was attempted; both research browser tabs were closed. The report treats promotion permission and karma/age thresholds as unknown. Signed-out X/Reddit and r/codex’s no-bots exclusion remain Sam-supplied constraints, not a browser state newly checked here.

Detailed reproduction and sources are in the private report and `~/indicator-beta/promo-research-2026-10-08/`; project task is `docs/todo/done/product/promo-channel-research-2026-10-08.md`. Documentation validation and CI confirm tracking integrity, not editorial acceptance. Research is complete; ready to exit after final records agree. Do not start another Indicator task today, and do not exit the client automatically.
