---
title: "Minimize to tray with Claude 5-hour and Codex 7-day indicators"
status: now
area: product
due: null
updated: 2026-10-18
owner: agent
brief: "78f8448 pushed;531+31 tests and compatible fresh install passed locally; hosted CI running before app restart."
refs: ["claude_widget.py", "tests/test_widget_ui.py"]
test: null
---
- **What:** Main-window minimize must never open a closed terminal manager. Minimize to the desktop tray when available, with visible Claude 5-hour and Codex 7-day usage indicators that update from existing data. Preserve a recoverable screen-edge fallback when no tray host exists.
- **Why:** `claude_widget.py:10004` currently opens `TerminalTabsPanel` unconditionally whenever the tabs section is enabled; the header button calls that path instead of minimizing to tray.
- **Next:** Sole implementation agent edits window/tray behavior and focused tests; independent review follows. Run focused/full Python tests, task tests/drift, fresh-install verification and diff checks; commit/push; await green exact-revision CI; restart `claude-indicator.service` and verify native minimize/restore, both tray indicators, closed-manager invariant and service health. User explicitly requested the restart on October 18.

## Scope and evidence

- Start: clean `master` equals `origin/master` at `0272298`; existing service active with PID 8248 and main-checkout ExecStart. Existing minimization uses an edge sliver and opens the terminal panel; tray currently displays a Smart TODO compass only.
- No new provider adapter, direct authenticated probe, billing, account action, outreach or upstream contribution is needed. Existing provider refreshes continue normally when the app is restarted. External verification clock: hosted Python/install and repository guard runs after the code push. Native tray/window behavior must be checked after deployment.
- Done means the requested behavior is implemented, tested, independently reviewed, pushed with green CI, deployed through the existing user service, and verified on the desktop; generated TODO and shared memory agree with those receipts.

## October 18 implementation checkpoint

- Native baseline: X11 tray host is present; main window mapped, terminal manager and edge sliver both unmapped. No live app interaction or restart yet. Private cropped baseline evidence is under `~/indicator-beta/minimize-tray-2026-10-18/`.
- Sole implementer is replacing the compass with Claude C and Codex X quota icons, adding header/native minimize routing, and retaining sliver recovery only when needed. Existing polling results supply all data; no new provider request path. Parent inspected 22px and 32px icon previews: provider letters, quota numbers, unavailable question mark and cache dot are distinguishable. Tests/review remain pending; these previews are not deployment proof.
- Task workflow passed 25 tests and generated-state check (13 tasks). Planning checkpoint `cc456d47cac3ae0b85aaebcaced5c25bb4ddb7c0` has green repository guard run 39144295197.

## Local validation and review

- Frozen implementation covers header and native minimize-to-tray, closed-manager preservation, two visible C/X quota icons from existing polling data, actual duration-selected Codex weekly quota, unavailable/error/reset/expiry states, cached age marking, hidden-window updates, shared existing menus, restore, host-loss fallback and shutdown. README explains usage. No adapter or new provider call was added.
- Final full offline suite with isolated HOME passed **530 tests +31 subtests in 6.74s**, exit 0. Implementer widget suite passed **160 tests +24 subtests**; independent reviewer passed **28 focused tests +14 subtests** and approved the frozen diff without actionable findings. `git diff --check` passed. Receipt: `~/indicator-beta/minimize-tray-2026-10-18/full-tests-final.log`.
- Final clean-install smoke passed 8 installed modules, help/version and an inert 340x753 widget, with HTTP/subprocess creation blocked (Python 3.13.9, PySide6 6.12.0). This second fresh install started after the last host-loss fix and validates the frozen source. Receipt and rendered image: `~/indicator-beta/minimize-tray-2026-10-18/install-validation-final.json` and `install-widget-final.png`. No live service was changed during installation tests.
- Next: commit/push source and this task, observe exact-source Python/install plus repository guard CI, then restart the existing user service and verify native minimize/restore and both indicators. Runtime is still the pre-task process until that explicit deployment step.

## Pushed checkpoint

- Source `89cea8a91e488d85a2501cba1e2ab32b5b31838d` is pushed to `origin/master`; working tree was clean after push. Widget SHA-256: `54228b9aec5e4a8491431af52f50f6c1026c062985d1d16220f6da3c3cd910a7`.
- Exact-source repository guard [39144830445](https://github.com/samuelfrench/claude-indicator/actions/runs/39144830445) passed. Python/install [39144830504](https://github.com/samuelfrench/claude-indicator/actions/runs/39144830504) finished with **530 tests +31 subtests passed in 11.15s**, then `QObject: shared QObject was deleted directly` and interpreter segmentation fault (exit139); installation was skipped. Same teardown signature was previously recorded at `db215ed` in the completed promotion-research task. The failed receipt is retained at `~/indicator-beta/minimize-tray-2026-10-18/hosted-ci-failed.log`; reproduce with `gh run view 39144830504 --log-failed`.
- Scoped prerequisite is now dependency compatibility diagnosis/guarding to unblock actual full CI; no workflow failure suppression or provider work. Sole implementer owns this fix; independent review and renewed full gates follow. App restart remains pending until green CI.
- Local reproduction matches hosted behavior: isolated HOME, Python3.10.19, PySide6/shiboken6 6.12.0, pytest9.1.1 and pytest-subtests0.15; all **530 tests +31 subtests** pass before the same shared-QObject warning and exit139. Reproduction environment `/tmp/claude-indicator-qt310`; private receipt `~/indicator-beta/minimize-tray-2026-10-18/qt310-before-cleanup.log`. Default Python3.13/PySide6 6.10.2 does not reproduce it.
- **Rejected explanation/fix:** Qt fixture/deferred-delete cleanup alone did not fix the crash. A standalone QApplication plus quota-icon rendering loop, without pytest or widget fixtures, reproduces `none_dealloc`; None's reference count fell **33784 to 31022**. Repeating individual void mutators 100 times (setPen/setBrush/drawRect/QFont.setPixelSize) loses **100 None references**, while object-returning drawText/toImage operations lose 0. Ineffective fixture changes are being removed. This is a binding compatibility defect rather than evidence of a tray-feature ownership bug.
- **External evidence/next:** Qt's [development notes](https://wiki.qt.io/Qt_for_Python_Development_Notes), August20 entry, link existing PYSIDE-3424 for Python3.12-built abi3 wheels on Python3.10 and differing INC/DECREF behavior. No new upstream post is needed. Measure older Qt versions on Python3.10, apply the narrow compatible package dependency guard supported by those results, add a subprocess regression check and review it. Do not remove Python3.10 support, skip tests, suppress process errors, or replace a full CI run with assertion counts.
- Existing service is still active/running PID 8248 with 0 automatic restarts. Next after green CI: `systemctl --user restart claude-indicator.service`, verify changed PID/current source, use the real header minimize control, confirm main/terminal/sliver windows are unmapped and both quota icons visible, then restore from each icon and confirm manager stays closed. Capture only private app/tray crops and scoped service/error evidence under `~/indicator-beta/minimize-tray-2026-10-18/`.

## Measured compatibility guard

- Standalone 1000-call QFont probe on Python3.10.19: PySide6 **6.12.0 loses1000 None references and exits134**, while **6.11.2 and6.10.2 lose0 and exit0**. Exact scripts/receipts: `~/indicator-beta/minimize-tray-2026-10-18/qt_binding_probe.py`, `qt310-{610,611,612}-probe.log`.
- Both `pyproject.toml` and `requirements.txt` now exclude **only PySide6 6.12.0 on Python<3.12**; newer Python constraints stay unchanged. Added `tests/test_widget_runtime.py::test_qt_void_calls_preserve_none_references_and_exit_cleanly` to catch reference loss in a child process and require a clean exit. The probe fails on the bad binding, passes on both measured healthy releases, and does not suppress failures. Ineffective fixture changes were fully reverted.
- Independent compatibility review approved all4 changed files without findings. Root full isolated suites each passed **531 tests +31 subtests**: default Python3.13.9/PySide6 6.10.2 in6.50s and Python3.10.19/PySide6 6.11.2 in6.79s, both exit0. Receipts: `full-tests-compat-default.log` and `full-tests-compat-qt611.log`. Earlier root recheck of the intentionally bad6.12 environment failed the new probe as expected; it is not the healthy environment.
- Final local Python3.10 fresh install **passed**, resolving PySide6 **6.11.2**, importing all8 modules from installed site-packages, passing help/version and rendering the inert340x753 widget with HTTP/subprocesses blocked. Image inspected. Receipt `install-compat-validation.json` records the local adaptation: uv standalone Python needs a **symlinked** bootstrap venv; stock copied interpreters cannot locate `/install/lib/python3.10/encodings`. Same verifier ran with only `EnvBuilder(symlinks=True)` adapted locally. No repository verifier change or CI workaround; unmodified verifier must still pass on hosted Python3.10.
- Compatibility source **78f8448e36be48e7f079be6150da44c89d696009** is pushed; both [Python/install39145804950](https://github.com/samuelfrench/claude-indicator/actions/runs/39145804950) and [repository guard39145804944](https://github.com/samuelfrench/claude-indicator/actions/runs/39145804944) are live. Observe existing runs; no app restart yet. Application bytes still match feature89cea8a and the widget SHA256 above.
