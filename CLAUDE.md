# Claude Indicator development context

Claude Indicator is a Linux PySide6 desktop widget. `claude_widget.py` contains provider clients, local readers, painted rows, worker timers and the main widget. `smart_todos.py` plus `smart_todo_workflow.py` contain the local TODO command center and state; `terminal_recovery.py` plus `terminal_recovery_ui.py` contain private terminal inventory and recovery UI. `widget_runtime.py` contains process singleton locking and optional systemd readiness/watchdog behavior. `indicator_cli.py` provides the packaged command and performs help/version handling before Qt imports.

## Task tracking

`TODO.md` and `docs/todo/index.json` are generated from task sources in `docs/todo/`. Read TODO and the linked task before changing work. Update its source in the same working beat as scope, status, evidence or blocker changes; run `node scripts/todo/build.mjs` and commit the source plus both outputs together. Never hand-edit generated task state. Use `node scripts/todo/query.mjs --status now,waiting-sam` to resume; rules are in `docs/todo/README.md`.

## Beta boundaries and evidence

Current beta scope, policy classifications and data-flow qualifications are recorded in `docs/todo/product/beta-phase-1.md`, `docs/beta/provider-terms-check.md` and `docs/beta/privacy-audit.md`. No public launch, posting, provider testing requests, new billing or live widget restart is authorized by the beta validation lane. Use mocked responses and isolated installation smoke checks. The README is the user-facing install/platform contract.

## Implementation rules

- PySide6 and requests are the package dependencies. Package all seven root application modules in `pyproject.toml`; do not accidentally include personal state, documents or service configurations in the wheel.
- Informational CLI commands must exit before Qt import, credential reading, provider communication or state writes. Installation must not start the GUI or alter autostart/systemd.
- Credential-bearing HTTPS requests go to their provider endpoint. Keep credentials out of logs, history and UI errors. Local subprocesses and browser/editor/clipboard actions have separate data-flow qualifications in the privacy audit.
- Hidden provider rows skip their fetches. Missing/error quota data is unavailable, not zero. Cached usage must show age and respect expiry/reset bounds.
- Keep private state confined to user-controlled locations. Do not commit live logs, tokens, tasks, personal screenshots or workflow documents.
- XWayland is selected under a Wayland session with DISPLAY for positioning, docking and xdotool navigation. Native Wayland is unsupported by the beta.
- Keep child Qt workers alive through bounded shutdown; replacing a running QThread can abort the process. Keep intentional Quit/SIGTERM closed even when optional supervision is installed.
- Generalize optional task groups through `TASK_GROUPS_CONFIG`; the distributed default is empty. Do not hardcode a user's private project list.

## Gates

Run focused tests then `QT_QPA_PLATFORM=offscreen python3 -m pytest -q`, `node --test scripts/todo/__tests__/todo.test.mjs`, `node scripts/todo/build.mjs --check`, `python3 scripts/verify_install.py` and `git diff --check`. Tests block unmocked requests/urllib calls. The installation verifier uses a fresh venv and isolated HOME without launching the actual app. Repository guards and Python CI must pass before merging/pushing completion evidence. This desktop beta deliberately leaves the owner's live service untouched.

## Optional source helpers

`scripts/indicator_service.py` installs or launches an optional user service plus graphical-login desktop entry. The helper detects checkout and Python paths; installation renders files and reloads systemd without starting the widget. The service uses Qt event-loop readiness/heartbeat, singleton locking, failure restart after five seconds, a 90-second watchdog and bounded stop behavior. Run it only when user scope authorizes service changes. `scripts/ollama_watchdog.py` and `scripts/user/` are optional source tooling, excluded from normal installation.
