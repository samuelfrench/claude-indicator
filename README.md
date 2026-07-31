# Claude Indicator

A translucent desktop widget for Linux that displays your Claude Code Max subscription usage in real time plus your local Codex usage-limit percentage. Shows color-coded progress bars for rate limit windows with live countdown timers.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.6+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Real-time usage tracking** — monitors 5-hour and 7-day rate limit windows
- **Model-specific limits** — shows Opus or Sonnet 7-day utilization when available
- **Codex limit percentage** — shows current Codex 5-hour usage percentage, 7-day percentage, latest-thread tokens, and lifetime local totals from cached local Codex state
- **Expandable Cron Manager** — reads the current user's crontab and journal entries, lists each job, and shows live status (`ok`, `late`, `unknown`) with last run + next scheduled run
- **Smart TODO command center** — captures an overall inbox task and ranks TODOs from local workspaces from the tray
- **Color-coded progress bars** — green/yellow/orange/red based on usage percentage
- **Live countdown timers** — shows time remaining until each window resets
- **Always-on-top translucent widget** — frameless, draggable, stays visible over other windows
- **Auto-refresh** — polls the API every 5 minutes, countdowns update every second
- **OAuth token management** — reads credentials from Claude Code and handles token refresh automatically

## Screenshot

The widget displays a dark translucent overlay with:
- "CLAUDE MAX" header in warm gold
- Up to 3 progress bars (5-Hour Window, 7-Day Window, Model-specific 7-Day)
- A compact `CODEX` row with current Codex limit percentage and local usage totals
- `CRON JOBS` row that collapses to one line and expands to show per-job status and timing
- Percentage and reset countdown on each bar
- Last-updated timestamp and manual refresh button

## Cron Manager behavior

- **What appears**: one collapsed row labeled `CRON JOBS` with a late-job count summary
- **Expand**: click the row to expand a compact list of user cron jobs
- **Job status meanings**:
  - `ok` — matched a recent journal execution for the expected previous schedule slot (with 180s grace)
  - `late` — cron job is overdue relative to the expected next/previous run window within the available journal history
  - `unknown` — no reliable evidence in the collected 48h journal window
- **Per job fields**: label (from inline/full-line comments or fallback to command), schedule, last run age (`just now`, `Xm ago`, `Xh ago`, `Xd ago`), and next run estimate for common 5-field cron patterns
- **Data source**: `crontab -l` for job definitions and `journalctl _COMM=cron` for command execution history
- **Refresh interval**: every 5 minutes

## Smart TODO command center

Open the tray menu and select **Smart TODOs…**. The modeless command center is
created on first use and reused after that, so the main Indicator can stay visible
or hidden independently.

### Capture and completion

- Enter a task, optionally clear **No due date** and choose a date, then select
  **Add task**.
- Captured tasks are written only to the `Indicator Inbox` section of
  `~/TODO.md`, between `<!-- claude-indicator:inbox:start -->` and
  `<!-- claude-indicator:inbox:end -->`. The Indicator owns only that marked
  section and preserves the rest of the file.
- Only open tasks inside the single valid managed section in the exact injected
  home TODO have a **Complete** control. Matching Indicator IDs in project TODOs
  or elsewhere in the home file are ignored.
  Project TODO entries are read-only in the command center.
- **Open source** opens the selected file at its Markdown line when `code`,
  `codium`, or `gedit` is available, and otherwise opens the file with
  `xdg-open`. No shell command is constructed.

### Views and ranking

- **Focus** shows open, actionable tasks. **All open** also includes waiting
  work. **Waiting** isolates blocked or time-gated items. **Completed inbox**
  shows completed entries owned by the Indicator.
- Waiting recognition includes `blocked by owner`, `blocked-by-owner`, and
  future `on or after`, `no earlier than`, `only after`, or `until` dates.
- Search covers task text, project, heading, tags, and ranking reasons. The
  project filter narrows results to one discovered project; **Reset** restores
  the Focus view across all projects.
- Ranking is explainable in the **Why now** rail. Signals include explicit due
  dates, P0/P1 and urgent language, revenue or customer impact, billing or cost
  exposure, production verification work, and overall-inbox capture. Explicit
  waits and future `on or after` / `no earlier than` gates remain outside Focus
  until actionable.

### Local data boundary

The scanner reads `~/TODO.md` plus `TODO.md` files at bounded depth under
`~/claude-workspace` and `~/codex_workspace`. It skips hidden, dependency,
build, cache, coverage, test-output, and nested worktree directories, caps the
rendered result set, and reports unavailable roots, unreadable or oversized
files, symlinks, and special files in the dialog. Workspace candidates remain
confined beneath their resolved configured root.
All scanning, ranking, filtering, persistence, and source navigation stay on
this computer. Smart TODOs adds no API calls, hosted service, subscription, or
billable usage.

## Prerequisites

- **Claude Code Max subscription** — the widget reads usage data from Anthropic's API
- **Claude Code CLI** — must be installed and logged in (the widget reads OAuth credentials from `~/.claude/.credentials.json`)
- **Python 3.10+**
- **Linux with X11 or Wayland** (tested on Ubuntu/GNOME)

## Installation

```bash
git clone https://github.com/yourusername/claude-indicator.git
cd claude-indicator
pip install -r requirements.txt
```

### Dependencies

- `PySide6` >= 6.6.0 — Qt6 bindings for the desktop widget
- `requests` >= 2.31.0 — HTTP client for API calls

## Usage

```bash
python claude_widget.py
```

The widget appears in the top-right corner of your primary screen. Drag it to reposition. Click the **X** to close or **⟳** to force a refresh.

### Autostart on Login

To launch the widget automatically on login, create `~/.config/autostart/claude-widget.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Claude Usage Widget
Exec=/path/to/python3 /path/to/claude_widget.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
```

> **Note**: If using conda/miniconda, use the full Python path (e.g., `/home/user/miniconda3/bin/python3`) since `~/.bashrc` is not sourced by autostart.

### Troubleshooting

If you see an error about `xcb-cursor`, set the library path before running:

```bash
LD_LIBRARY_PATH=/path/to/miniconda3/lib python claude_widget.py
```

## How It Works

1. **Reads OAuth credentials** from `~/.claude/.credentials.json` (written by Claude Code CLI)
2. **Refreshes the access token** if it's within 5 minutes of expiry, using the OAuth refresh flow
3. **Fetches usage data** from `GET https://api.anthropic.com/api/oauth/usage` with the `anthropic-beta: oauth-2025-04-20` header
4. **Reads local Codex usage** from `~/.codex/state_*.sqlite` and cached session `token_count` events under `~/.codex/sessions/`
5. **Builds cron health** from `crontab -l` plus `journalctl` execution logs, using command equality and local-time schedule prediction
6. **Scans local TODO files** on a background Qt worker and writes only the marked Indicator Inbox section in `~/TODO.md`
7. **Renders the widget** using PySide6 with custom-painted progress bars, translucent panels, collapsible custom rows, and a modeless Smart TODO dialog

### Architecture

The application uses `claude_widget.py` for the Indicator and `smart_todos.py`
for the local TODO domain and dialog, with these components:

| Component | Description |
|---|---|
| `ClaudeUsageClient` | Handles OAuth credential reading, token refresh, and API calls |
| `FetchWorker` | QThread that fetches usage data off the main thread |
| `UsageBar` | Custom-painted widget for a single progress bar with label, percentage, and countdown |
| `CodexUsageRow` | Custom-painted summary row backed by local Codex SQLite state and cached rate-limit events |
| `CronJobsWidget` | Collapsible row showing per-job cron health, last run age, and next run estimate |
| `CronJobsFetchWorker`, `CronJobInfo` | Background worker and model used to parse crontab + journal history |
| `Cron parsing helpers` | Parsers for `crontab -l`, schedule matching, and journal matching |
| `ClaudeWidget` | Main frameless, translucent, always-on-top widget with drag and tray support |
| `SmartTodoDialog`, `TodoScanWorker` | Modeless command center and background local TODO scanner from `smart_todos.py` |
| `UsageData` / `UsageEntry` | Dataclasses modeling the API response |

### Color Thresholds

| Usage | Color |
|---|---|
| 0–49% | Green |
| 50–74% | Yellow |
| 75–89% | Orange |
| 90–100% | Red |

## License

MIT
