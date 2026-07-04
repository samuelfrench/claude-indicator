# Claude Indicator TODO

- [x] Show the Fable-specific usage limit: parse the `/api/oauth/usage` `limits` array (model-scoped `weekly_scoped` entries) and render one `UsageBar` per model cap — currently `Fable (7-Day)` — with legacy `seven_day_opus`/`seven_day_sonnet` fallback and `last_usage.json` round-trip.
- [x] Add header minimize-to-tray button plus shared tray hide/show behavior.
- [x] Show Codex usage-limit percentage: `CodexUsageRow` now reads cached `token_count` rate-limit events from `~/.codex/sessions/**/*.jsonl` on a background worker and displays current 5-hour plus 7-day usage percentages.
- [x] Keep startup visible and avoid hidden tray-only behavior: force initial sizing/raise and only hide-on-close when tray is available.
- [ ] Watch for future Codex state schema changes; `read_latest_codex_rate_limit()` intentionally reads cached JSONL events rather than making live network/API calls.
