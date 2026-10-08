# Beta installation validation — 2026-10-07

The beta package provides `claude-indicator` without starting the application or modifying autostart/systemd. The advertised command is `pipx install git+https://github.com/samuelfrench/claude-indicator.git` after Python 3.10+, pipx and Git are installed. Supported platforms are Linux with X11 or XWayland; native Wayland, macOS and Windows are unsupported. Qt/XCB system libraries come from the user's distribution; Ubuntu may need `libxcb-cursor0`. Optional CLI/provider credentials, NVIDIA, Ollama, ComfyUI and systemd are not installation requirements.

## Local clean-environment proof

`python3 scripts/verify_install.py` created a fresh virtual environment without system site packages and an isolated home/config/data/state/cache/runtime directory. Provider credential environment variables, display/session authentication, notification sockets and inherited provider CLI homes were removed or redirected. The installed command was tested from a temporary directory outside the checkout. Both `--help` and `--version` succeeded before Qt/widget import; the version was `claude-indicator 0.1.0b1`.

All seven application modules were imported from the new environment's installed `site-packages`: `indicator_cli`, `claude_widget`, `smart_todos`, `smart_todo_workflow`, `terminal_recovery`, `terminal_recovery_ui` and `widget_runtime`. With all Python HTTP calls and subprocess creation blocked, the real installed `ClaudeWidget` was constructed, shown and rendered through Qt offscreen at **340×705**. Fetchers, timers, tray setup and the system-metrics constructor were replaced by inert mocks. The source's system-metrics constructor reads `nvidia-smi`, so the harness mocks that constructor as well; the guard caught the first attempt and no subprocess ran. Final proof passed on **Python 3.13.9 / PySide6 6.11.2**.

This proves fresh installation, command generation, packaged-module completeness and inert Qt startup/rendering. It does not prove a native compositor/tray/terminal-navigation integration or successful authenticated provider calls; those are deliberately outside this clean beta test. The existing owner widget and user services were not started, stopped, restarted or reconfigured. No Anthropic generation or provider quota request was made. Package installation only downloaded build/runtime dependencies through pip.

## Gates and remote proof

The isolated focused gate passed **217 tests plus 9 subtests**. The final full isolated local gate passed **462 tests plus 14 subtests in 7.43 seconds**. GitHub CI and remote installation evidence remain pending the tested push. The task-workflow suite passed **25 tests**, generated TODO/index drift checks passed, and signup/feedback/config/workflow YAML parsed successfully. Quote permission is optional and unchecked by default.

Repository CI runs unit tests with isolated user state plus the fresh-environment package/render verifier, using Python 3.10 on Ubuntu. Remote Git installation evidence will be added after the tested privacy-cleaned commit is pushed, so the tested Git source matches the advertised command. No release or public launch is part of this work.
