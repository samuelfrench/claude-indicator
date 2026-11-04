---
title: Automatically sync Crons with Cron Manager
status: done
area: product
due: null
updated: 2026-11-04
owner: agent
brief: Live shared snapshot polling verified across all 183 observed jobs; stale and partial states remain explicit.
test: tests/test_cron_jobs.py
refs:
  - claude_widget.py
  - tests/test_cron_jobs.py
---

## What / Why / Next

The existing Crons section reads only the user crontab and infers trigger health; Cron Manager aggregates scheduler inventory and recorded results at `http://127.0.0.1:4741/api/snapshot`. Make that snapshot the widget's source of truth, poll automatically every minute, retain source result/enablement semantics, and expose stale/unavailable collection state. Keep the expanded inventory usable with the larger job count. No scheduler changes or job execution are authorized or needed.

Implemented shared snapshot polling every 60 seconds, all-source inventory and disabled/result semantics, retained stale rows during outages, coverage and snapshot-time details, and ten-row paging. Focused tests cover automatic timer/worker update-removal, outage/recovery, visibility and paging. Local isolated-HOME full suite: 577 passed, 49 subtests; TODO gates: 25 passed and drift clean; fresh-package inert install/render passed. Running the suite with the real HOME first exposed eight unrelated provider-adapter expectations overridden by the owner statusline opt-in; use the isolated environment in `scripts/verify_install.py` or CI. Independent review found and fixed the Next-label hit area before release. Offscreen live-snapshot render: 183 jobs, expanded 340x222, private audit under `~/.local/share/claude-indicator/audits/cron-sync-20261104/`.

Completed: code `44b14e3943679dcef23e538d6f71f9be66c90895` pushed; independent review passed after the paging fix; Python CI `41896379691` and repository guards `41896379836` green. Deployed through `systemctl --user restart claude-indicator.service` on November 4 at 13:24 CT. Native screenshot shows the 183-job Crons row, partial coverage and result counts. Service PID 257632 is active, zero restarts, no error-level journal entries. Actual snapshot callbacks at 13:24:11 and 13:25:29 CT received 183 jobs with advancing generated timestamps, proving automatic polling beyond startup (collector refresh can delay the response). Live adapter/API parity checked every job ID, name, status, enablement, source, schedule and description. The private audit directory contains `live-parity.json`, `install-validation.json`, offscreen expanded and native live screenshots.

Shared note: `~/.codex/memories/extensions/ad_hoc/notes/20261104T192548Z-codex-cron-manager-sync-live-2af67e6f.md`, linked into the exact Claude project memory. No remaining implementation or deployment work. Cron Manager must remain running; its partial/unavailable sources stay explicit and API outages retain stale rows until recovery. Counts and PID above are dated observations. No scheduler mutations or new billing. Reproduce with the focused cron tests, isolated-HOME repository gates and `rg "cron snapshot:" ~/.claude/widget.log`; compare inventory with the read-only API.
