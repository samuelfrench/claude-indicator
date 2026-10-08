# Claude Indicator

A translucent Linux desktop widget for Claude and Codex usage, DeepSeek spend and credit, MiniMax/OpenCode Go/SuperGrok quotas, local system activity, and Ollama/GPU/ComfyUI status.

**Local desktop monitoring with no Indicator telemetry. Credentials go to their providers; the Indicator does not upload your task text or saved terminal history.** See the [privacy audit](docs/beta/privacy-audit.md) for network destinations, local storage and qualifications. Provider integrations have different policy constraints; read the [provider terms check](docs/beta/provider-terms-check.md) before enabling them or distributing a paid version.

## Beta

With Python 3.10+, [pipx](https://pipx.pypa.io/stable/installation/) and Git installed, install in one command:

```bash
pipx install git+https://github.com/samuelfrench/claude-indicator.git
```

Installation creates the `claude-indicator` command. It does not launch the widget, install autostart entries, or change systemd services. Check `claude-indicator --help` or `claude-indicator --version`, then run `claude-indicator` in your graphical session. To upgrade, use `pipx upgrade claude-indicator`; to remove it, use `pipx uninstall claude-indicator`.

The beta supports **Linux with X11 or XWayland**, tested on Ubuntu/GNOME. It depends on Linux `/proc` and `/sys`; macOS, Windows and native Wayland are unsupported. Under Wayland, XWayland and a valid `DISPLAY` are required for reliable positioning and terminal navigation. On Ubuntu, Qt requires the EGL runtime (`sudo apt-get install libegl1`), including for offscreen tests; graphical sessions may also need XCB libraries such as `libxcb-cursor0`. GNOME Terminal supports exact TTY selection; other terminal emulators use a limited best-effort path. NVIDIA, Ollama, ComfyUI, systemd and individual AI CLIs are optional features rather than installation requirements.

Use the [beta signup form](https://github.com/samuelfrench/claude-indicator/issues/new?template=beta-signup.yml) to share your paid AI plans, wanted providers and OS, and the [beta feedback form](https://github.com/samuelfrench/claude-indicator/issues/new?template=beta-feedback.yml) for what worked and broke. Issues are public: omit tokens, account identifiers, private tasks and unredacted logs/screenshots. Permission to quote feedback is optional and unchecked by default.

## Provider data and credentials

The widget reuses credentials or local data from tools you have already configured. No account or provider subscription is created by installation. Missing credentials show unavailable data. The Configure menu can hide individual sections and provider rows; hidden providers skip their fetches.

| Provider | Current data source |
|---|---|
| Claude | Claude Code OAuth credentials; usage endpoint, OAuth refresh, or a minimal inference request whose response headers contain quotas |
| Codex | Local `codex app-server` account rate-limit protocol, recent local session cache and local SQLite totals |
| DeepSeek | Official balance endpoint plus local OpenCode cost ledger |
| MiniMax | Coding-plan quota endpoint plus local OpenCode token ledger |
| OpenCode Go | Go usage endpoint using the existing OpenCode key |
| SuperGrok / Grok Build | CLI billing endpoint using Grok CLI or OpenCode OAuth; no Grok token refresh |
| Ollama / ComfyUI | Loopback status endpoints; local OpenCode ledger for model token totals |

Claude's header fallback sends a real `max_tokens: 1` Haiku request to Anthropic and consumes subscription usage. The application cannot guarantee that a user's plan has overage disabled. Header-only mode lacks model-specific limits and extra-usage dollars. No new Anthropic requests were made for beta testing; validation uses mocks. Current OAuth/undocumented-source policy risks are documented in the terms check.

API keys can be provided through `DEEPSEEK_API_KEY`, `MINIMAX_API_KEY` and `OPENCODE_GO_API_KEY`, or read from owner-controlled mode-0600 OpenCode auth. Grok uses `GROK_OAUTH_TOKEN`, its owner-controlled CLI auth file, or OpenCode OAuth. Claude uses its existing CLI credentials and optionally `CLAUDE_CODE_OAUTH_TOKEN` or the private `~/.credentials/claude-oauth-token.txt`. Do not paste any of these values into issues. HTTPS requests send the relevant credential to that provider; Codex's CLI manages its own provider communication.

## Local features and storage

The widget shows quota bars and reset countdowns, 24-hour usage history, expandable local AI and system rows, current-user cron health, optional deployment/runner status, and a docked terminal selector with notes and park state. A Traffic Report shortcut opens `http://127.0.0.1:5173/` in your default browser; the separate server must already be running.

**Terminal recovery** records the current user's terminal identities, working directories, program names and first/last observation times every five seconds. Live, Last boot snapshot and All saved views support search and copying details. The private SQLite database at `~/.local/state/claude-indicator/terminals.sqlite3` persists across restarts and reboots without automatic expiry. It records work, not scrollback, and does not restart commands. Saved recovery data excludes command arguments and environment variables; other process inspection uses command lines in memory to identify relevant running tools.

**Smart TODOs** is opened from the tray. It reads `~/TODO.md` and bounded project TODO files under `~/claude-workspace` and `~/codex_workspace`, supports deterministic ranking, Today, pins, snooze, dismiss/restore, project filters and Copy Context, and stores local workflow choices. Add/Complete writes only the managed `<!-- claude-indicator:inbox:start -->` / `<!-- claude-indicator:inbox:end -->` section in `~/TODO.md`; project TODO sources stay read-only. Source navigation can open a local editor, and Copy Context places selected task text on the clipboard.

Usage snapshots, history, visibility, terminal notes and Smart TODO state live under `~/.claude/`; terminal recovery and singleton state live under the user's local state/runtime directories. Local files can contain private work details or usage totals; manage them as user data. The privacy audit distinguishes mode-0600 stores from legacy files that inherit the user's umask.

## Source checkout and optional supervision

For development, clone this repository and run `python3 -m pip install '.[test]'`. Run the source widget with `python3 claude_widget.py`; the packaged `claude-indicator` command offers display validation and safe help/version commands.

The source-only `scripts/indicator_service.py` helper optionally installs a supervised graphical-login user service and desktop launcher. Installing or launching supervision is a separate action; the beta installer does neither. The helper detects the checkout and interpreter. Its service has a singleton lock, Qt readiness/heartbeat, failure restart and bounded shutdown. Tray Quit and SIGTERM are intentional clean exits.

```bash
python3 scripts/indicator_service.py install --python "$(command -v python3)"
python3 scripts/indicator_service.py launch
```

The optional Ollama watchdog in `scripts/ollama_watchdog.py` and `scripts/user/` is source-only tooling. No watchdog or autostart timer is installed by the package.

## Verification

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q
node --test scripts/todo/__tests__/todo.test.mjs
node scripts/todo/build.mjs --check
python3 scripts/verify_install.py
```

Tests block unmocked Python HTTP requests. The installation verifier creates a fresh virtual environment and isolated home, installs the local project, checks the installed command and modules, and renders an inert offscreen widget with fetchers disabled. It never starts or restarts an existing widget. See [installation evidence](docs/beta/install-validation.md) for the current result and limits.
