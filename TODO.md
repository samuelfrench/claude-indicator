# Claude Indicator TODO

- [x] Read task-loop status from local configuration only; no longer scan DynamoDB every 60 seconds.
- [x] Document the controlled `mergepdfnow.com` registrar contact-recovery exception and hash-verified immutable-field rule without storing an address or other PII.
- [x] Complete and review the immediate Cloudflare cutover for all 16 active Route 53 zones while leaving every source zone intact.
- [ ] Delete the 16 Route 53 source zones only after `2026-07-20T15:18:57.201000Z`, each rolling stale-cache clock, a 13-round/one-hour resolver clean window, and both full delayed gates pass.
- [x] Show the Fable-specific usage limit: parse the `/api/oauth/usage` `limits` array (model-scoped `weekly_scoped` entries) and render one `UsageBar` per model cap — currently `Fable (7-Day)` — with legacy `seven_day_opus`/`seven_day_sonnet` fallback and `last_usage.json` round-trip.
- [x] Add header minimize-to-tray button plus shared tray hide/show behavior.
- [x] Show Codex usage-limit percentage: `CodexUsageRow` now reads cached `token_count` rate-limit events from `~/.codex/sessions/**/*.jsonl` on a background worker and displays current 5-hour plus 7-day usage percentages.
- [x] Keep startup visible and avoid hidden tray-only behavior: force initial sizing/raise and only hide-on-close when tray is available.
- [ ] Watch for future Codex state schema changes; `read_latest_codex_rate_limit()` intentionally reads cached JSONL events rather than making live network/API calls.
- [x] Add the Smart TODO tray command center with global inbox capture, cross-project urgency ranking, safe source navigation, and local-only persistence. Shipped to `master`, verified against the real 34-file TODO corpus, and restarted in production via `claude-widget-codex.service`.
