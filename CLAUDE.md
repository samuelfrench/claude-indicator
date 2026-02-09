# Claude Indicator

## Project Description
Translucent PySide6 desktop widget showing Claude Code Max subscription usage limits with color-coded progress bars, a 24-hour usage graph, stats row, and countdown timers.

## Architecture
- **Single-file app**: `claude_widget.py` contains all logic (client, UI, timers, history)
- **ClaudeUsageClient**: Reads OAuth token from `~/.claude/.credentials.json`, fetches `GET https://api.anthropic.com/api/oauth/usage` with `anthropic-beta: oauth-2025-04-20` header
- **ClaudeWidget**: Frameless, translucent, always-on-top PySide6 widget with drag support (340x420)
- **UsageBar**: Custom-painted progress bars with color coding (green/yellow/orange/red)
- **UsageGraph**: QPainter line chart showing 5-hour utilization over last 24 hours with gradient fill, grid lines, and 80% threshold
- **StatsRow**: Compact custom-painted row with AVG, PEAK, TREND, and EXTRA usage stats
- **UsageHistory**: Persists data points to `~/.claude/usage_history.json` (max 288 points / 24h), atomic writes via os.replace()
- **Dynamic plan name**: Title detects CLAUDE MAX (opus present), CLAUDE PRO (sonnet present), or CLAUDE (neither)
- Token refresh via `https://platform.claude.com/v1/oauth/token` with client_id `9d1c250a-e61b-44d9-88ed-5944d1962f5e`

## Running
- May require `LD_LIBRARY_PATH=<path-to-miniconda>/lib` on some systems for xcb-cursor
- Autostart configured at `~/.config/autostart/claude-widget.desktop`
- Dependencies: PySide6, requests

## Key Decisions
- Uses `/api/oauth/usage` endpoint (not rate limit headers from `/v1/messages` which are locked to Claude Code sessions)
- OAuth tokens with `user:inference` scope work with this endpoint when `anthropic-beta: oauth-2025-04-20` header is included
- History stored in `~/.claude/usage_history.json` with atomic writes (write to .tmp then os.replace)
- Graph uses purple accent (#8b5cf6) with gradient fill and red dashed 80% threshold line
