# Claude Indicator TODO

- [x] Read task-loop status from local configuration only; no longer scan DynamoDB every 60 seconds.
- [ ] Recheck asynchronous S3 lifecycle execution until eligible payloads physically move: at `2026-07-13T16:46Z`, overflow still had `82,492` eligible Standard objects / `150,363,622,267` bytes and `37` eligible Standard-IA objects / `231,025,237,941` bytes with `0` Glacier; both backup payloads remained Glacier (`32` / `289,289,490,120` bytes and `2` / `110,036,590,284` bytes) with `0` Deep Archive. Lifecycle hashes remain exact; no payload mutation is required.
- [x] Document the controlled `mergepdfnow.com` registrar contact-recovery exception and hash-verified immutable-field rule without storing an address or other PII.
- [x] Complete and review the immediate Cloudflare cutover for all 16 active Route 53 zones while leaving every source zone intact.
- [ ] Delete the 16 Route 53 source zones only after `2026-07-20T15:18:57.201000Z`, each rolling stale-cache clock, a 13-round/one-hour resolver clean window, and both full delayed gates pass.
  - 2026-07-13 16:29 UTC pre-floor sample: `279/288` target-only, `6` old Route 53 answers across five domains, `3` empty/no-response observations, and `0` unexpected answers. All derived stale clocks remain earlier than the global floor; private state hash is `62e1834ed43e85b8dcc5df8c18ef5de8b9cb4883ccd994cda49f14ee85c33898` and deletion remains disabled `16/16`.
  - `BLOCKED_TIME_GATE` at `2026-07-13T16:54:56.670506Z`: `599,041` seconds remained before the hard floor. Fresh completion audit passed `16/16` registrar delegations, `208/208` `.com` authority checks, `16/16` active Free Cloudflare zones, exact `121/121` DNS-only records, `15/15` HTTPS/TLS endpoints, and exact `16/16` Route 53 sources; every deletion flag remained false and the clean window remained at round `0`.
- [x] Show the Fable-specific usage limit: parse the `/api/oauth/usage` `limits` array (model-scoped `weekly_scoped` entries) and render one `UsageBar` per model cap — currently `Fable (7-Day)` — with legacy `seven_day_opus`/`seven_day_sonnet` fallback and `last_usage.json` round-trip.
- [x] Add header minimize-to-tray button plus shared tray hide/show behavior.
- [x] Show Codex usage-limit percentage: `CodexUsageRow` now reads cached `token_count` rate-limit events from `~/.codex/sessions/**/*.jsonl` on a background worker and displays current 5-hour plus 7-day usage percentages.
- [x] Keep startup visible and avoid hidden tray-only behavior: force initial sizing/raise and only hide-on-close when tray is available.
- [ ] Watch for future Codex state schema changes; `read_latest_codex_rate_limit()` intentionally reads cached JSONL events rather than making live network/API calls.
