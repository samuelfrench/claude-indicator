# Claude Indicator TODO

- [x] Show Codex usage-limit percentage: `CodexUsageRow` now reads cached `token_count` rate-limit events from `~/.codex/sessions/**/*.jsonl` on a background worker and displays current 5-hour plus 7-day usage percentages.
- [ ] Watch for future Codex state schema changes; `read_latest_codex_rate_limit()` intentionally reads cached JSONL events rather than making live network/API calls.
