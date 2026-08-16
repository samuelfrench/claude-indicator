# Claude Indicator TODO

- [x] Read task-loop status from local configuration only; no longer scan DynamoDB every 60 seconds.
- [x] Document the controlled `mergepdfnow.com` registrar contact-recovery exception and hash-verified immutable-field rule without storing an address or other PII.
- [x] Complete and review the immediate Cloudflare cutover for all 16 active Route 53 zones while leaving every source zone intact.
- [ ] Delete the 16 Route 53 source zones only after `2026-07-20T15:18:57.201000Z`, each rolling stale-cache clock, a 13-round/one-hour resolver clean window, and both full delayed gates pass.
- [x] Show the Fable-specific usage limit: parse the `/api/oauth/usage` `limits` array (model-scoped `weekly_scoped` entries) and render one `UsageBar` per model cap — currently `Fable (7-Day)` — with legacy `seven_day_opus`/`seven_day_sonnet` fallback and `last_usage.json` round-trip.
- [x] Keep minimize recoverable: collapse the header button to a visible right-edge restore sliver while retaining shared tray hide/show behavior.
- [x] Show Codex usage-limit percentage: `CodexUsageRow` reads the live base `codex` bucket through local `codex app-server` `account/rateLimits/read`, renders only present windows, preserves local token/thread totals, and uses cached session `token_count` events only as a fail-safe.
- [x] Keep startup visible and avoid hidden tray-only behavior: force initial sizing/raise and only hide-on-close when tray is available.
- [x] Handle the current Codex rate-limit schema where the base bucket can expose one 7-day primary window and `secondary: null`, while retaining support for two-window responses.
- [x] Add the Smart TODO tray command center with global inbox capture, cross-project urgency ranking, safe source navigation, and local-only persistence. Shipped to `master`, verified against the real 34-file TODO corpus, and restarted in production via `claude-widget-codex.service`.
- [x] Add persistent Smart TODO dismiss state: `Dismiss` preserves every TODO source, hides finished tasks from active views and counts, and exposes them in `Finished` via local-only `~/.claude/smart_todos_finished.json` state.
- [x] Ship the full Smart TODO daily workflow release: seven-item Today docket with pins, snooze/wake, Restore, new/changed and duplicate review, project drill-down, Copy Context, conservative stale views, local-only atomic workflow state, and lock-screen-safe tray recovery.
- [x] Collapse the standalone Ollama indicator into a compact expandable Local AI section in this panel, reusing local GPU and task-loop data and adding Ollama/ComfyUI REST status without DynamoDB polling.
- [x] Add a DeepSeek row with rolling 24-hour OpenCode-recorded API spend, official current account credit, secure credential fallback, and conservative atomic balance-snapshot estimates.
