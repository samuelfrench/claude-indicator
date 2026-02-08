# Claude Indicator

A translucent desktop widget for Linux that displays your Claude Code Max subscription usage in real time. Shows color-coded progress bars for rate limit windows with live countdown timers.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.6+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Real-time usage tracking** — monitors 5-hour and 7-day rate limit windows
- **Model-specific limits** — shows Opus or Sonnet 7-day utilization when available
- **Color-coded progress bars** — green/yellow/orange/red based on usage percentage
- **Live countdown timers** — shows time remaining until each window resets
- **Always-on-top translucent widget** — frameless, draggable, stays visible over other windows
- **Auto-refresh** — polls the API every 5 minutes, countdowns update every second
- **OAuth token management** — reads credentials from Claude Code and handles token refresh automatically

## Screenshot

The widget displays a dark translucent overlay with:
- "CLAUDE MAX" header in warm gold
- Up to 3 progress bars (5-Hour Window, 7-Day Window, Model-specific 7-Day)
- Percentage and reset countdown on each bar
- Last-updated timestamp and manual refresh button

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
4. **Renders the widget** using PySide6 with custom-painted progress bars and translucent background

### Architecture

The entire application is a single file (`claude_widget.py`) with these components:

| Component | Description |
|---|---|
| `ClaudeUsageClient` | Handles OAuth credential reading, token refresh, and API calls |
| `FetchWorker` | QThread that fetches usage data off the main thread |
| `UsageBar` | Custom-painted widget for a single progress bar with label, percentage, and countdown |
| `ClaudeWidget` | Main frameless, translucent, always-on-top widget with drag support |
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
