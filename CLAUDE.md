# Claude Indicator

## Project Description
Translucent PySide6 desktop widget combining Claude Code Max and Codex usage,
DeepSeek API spend/credit, and compact local Ollama/GPU/ComfyUI status.

## Architecture
- **Single-file app**: `claude_widget.py` contains all logic (client, UI, timers, history)
- **ClaudeUsageClient**: Reads OAuth token from `~/.claude/.credentials.json`, fetches `GET https://api.anthropic.com/api/oauth/usage` with `anthropic-beta: oauth-2025-04-20` header
- **ClaudeWidget**: Frameless, translucent, always-on-top PySide6 widget with drag support and fixed 340px width
- **UsageBar**: Custom-painted progress bars with color coding (green/yellow/orange/red)
- **UsageGraph**: QPainter line chart showing 5-hour utilization over last 24 hours with gradient fill, grid lines, and 80% threshold
- **StatsRow**: Compact custom-painted row with AVG, PEAK, TREND, and EXTRA usage stats
- **CodexUsageRow**: Reads live Codex rate limits through the local `codex app-server` JSONL protocol (`account/rateLimits/read`), falls back only to unexpired cached `~/.codex/sessions/**/*.jsonl` token-count events at most five minutes old, visibly marks cached values, and combines them with `~/.codex/state_*.sqlite` latest-thread/lifetime totals; renders only the rate-limit windows the server provides
- **DeepSeekUsageRow**: Sums numeric DeepSeek assistant-message costs from the read-only local OpenCode SQLite ledger for rolling 24-hour spend and reads current credit from official `GET /user/balance` in a background thread
- **MinimaxUsageRow**: Reads MiniMax coding-plan quota from `GET https://api.minimax.io/v1/token_plan/remains` (`general` family) in a background thread, inverting the API's *remaining* percentages into 5-hour/weekly utilization, and pairs it with 24-hour token volume, message count, and latest model from the read-only local OpenCode SQLite ledger. The plan is a subscription, so OpenCode records `cost = 0` for every MiniMax message and no dollar figure is shown.
- **OpencodeUsageRow**: DeepSeek, MiniMax and ollama all write to the same read-only OpenCode SQLite ledger, so this row breaks the last 24 hours down per model — every line tagged with its provider (`minimax` / `deepseek` / `ollama`), with tokens, cost, and message counts — above a `LOCAL` line carrying today (since local midnight) and all-time local-model token volume plus the ledger start date. Collapsed it shows the 24-hour token total and the model count. MiniMax cost always reads `$0.00` because the coding plan is a subscription.
- **TerminalSessionsRow + TerminalTabsPanel**: The 22px `TABS` row summarises agent CLI sessions holding terminal tabs (`claude`/`codex`/`opencode` processes with a controlling pts, scanned from `/proc` every 15s, nested agents deduped via the ppid chain). A session is WORKING when its CPU delta beats a per-tool threshold (`TERMINAL_SESSION_TOOLS`) or it has a child forked >90s after session start (quiet tools like `gh run watch`); otherwise it is WAITING, and after 120s idle it flags NEEDS YOU. Clicking the row slides `TerminalTabsPanel` (420px, animated, docked) out from the widget's left edge (right edge when there is no room) and back in; the panel groups cards under NEEDS YOU / WAITING / WORKING / PARKED headers. Each card has a PARK/UNPARK button (parked sessions never flag and sort last), a persistent free-text note, and a clickable title that jumps to the hosting terminal tab — `focus_terminal_session` walks `/proc` to the terminal-emulator ancestor, matches window titles via xdotool, and falls back to activating the window and cycling tabs with XTEST `ctrl+Next` (verified focus only, unmatched windows restored with `ctrl+Prior`). Parked keys and notes persist to `~/.claude/terminal_sessions.json` (atomic, keyed `pid:starttime`, pruned when sessions exit). Card rebuilds are deferred while a note editor has focus. Only one `TerminalFocusWorker` runs at a time — replacing a live QThread is fatal.
- **LocalAISection**: Collapsed Ollama/GPU summary with expandable loaded-model, GPU/VRAM, ComfyUI, and local-config Ollama task-loop details; it does not query DynamoDB
- **DeepSeek balance history**: Currency-separated snapshots in `~/.claude/deepseek_balance_history.json` use a strict schema, mode `0600`, fsync, and atomic replacement
- **Expansion geometry**: Usage History and Ollama are mutually exclusive so
  the fixed-width panel remains usable on 800px-tall screens; DeepSeek remains
  independently expandable. `ClaudeWidget.adjustSize()` clamps the full frame
  into the primary screen's available geometry after every size change.
- **UsageHistory**: Persists data points to `~/.claude/usage_history.json` (max 288 points / 24h), atomic writes via os.replace()
- **Dynamic plan name**: Title detects CLAUDE MAX (opus present), CLAUDE PRO (sonnet present), or CLAUDE (neither)
- Token refresh via `https://platform.claude.com/v1/oauth/token` with client_id `9d1c250a-e61b-44d9-88ed-5944d1962f5e`

## Scripts
- `scripts/ollama_watchdog.py`: systemd-timer watchdog that restarts `ollama` after its
  scheduler has been wedged for 15 minutes. Detects the 0.32.14 deadlock signature — a model
  held past its keep-alive expiry, or a no-token load probe that hangs past 60s — without
  paying for a generation and without extending the model's keep-alive. Installed copies live
  at `/usr/local/bin/ollama-watchdog` and `/etc/systemd/system/ollama-watchdog.{service,timer}`;
  re-run the install command after editing the repo copy.
  On this host it currently runs as a **user** timer instead (`scripts/user/*`, linked into
  `~/.config/systemd/user/`), which needs no sudo because polkit lets an active session restart
  `ollama.service`. The user units run the repo script in place, so edits take effect on the next
  tick. `OLLAMA_WATCHDOG_RESTART_CMD` overrides the recovery command so the restart path can be
  exercised against a dummy unit without disturbing ollama.

## Running
- May require `LD_LIBRARY_PATH=<path-to-miniconda>/lib` on some systems for xcb-cursor
- Autostart configured at `~/.config/autostart/claude-widget.desktop`
- Dependencies: PySide6, requests
- DeepSeek credentials resolve from `DEEPSEEK_API_KEY` first, then the existing
  owner-controlled mode-`0600` OpenCode auth file; credentials are never stored
  in history, logs, labels, or tooltips

## Key Decisions
- Uses `/api/oauth/usage` endpoint (not rate limit headers from `/v1/messages` which are locked to Claude Code sessions)
- OAuth tokens with `user:inference` scope work with this endpoint when `anthropic-beta: oauth-2025-04-20` header is included
- History stored in `~/.claude/usage_history.json` with atomic writes (write to .tmp then os.replace)
- Graph uses purple accent (#8b5cf6) with gradient fill and red dashed 80% threshold line
- DeepSeek has no rolling-spend API: local OpenCode numeric request cost is the
  immediate 24-hour source; protected balance decreases are a marked fallback.
- Last-known DeepSeek credit is shown for at most 15 minutes and always includes
  its snapshot age; older snapshots remain history-only and are not displayed.
- MiniMax credentials resolve from `MINIMAX_API_KEY` first, then the same
  owner-controlled mode-`0600` OpenCode auth file (`minimax-coding-plan.key`);
  the key reaches only the Authorization header, never history, logs, or tooltips.
- Clawd task-loop rows remain local-configuration-only. The unified Ollama
  section reuses those results and adds no boto3/DynamoDB polling.
