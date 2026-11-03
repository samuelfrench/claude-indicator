---
title: "Refresh Claude local quota as soon as it arrives"
status: done
area: product
due: null
updated: 2026-11-03
owner: agent
brief: "Replace the five-minute local-feed delay with pickup on the existing one-second timer."
refs: ["03a7e038637bebe36fb38a6f2c400e38cda3bbe1"]
test: null
---
- **What:** Pick up changed local quota data promptly, keeping provider polling unchanged and preserving missing-window semantics.
- **Why:** The native widget last read an unavailable feed at 05:52:14 CT; a valid weekly-only observation arrived at 05:52:27, but the next automatic fetch was scheduled for 05:56:12. A direct local reader succeeds while the widget still displays Waiting for Claude Code quota. This is update latency, not missing OAuth authentication.
- **Next:** None for this repair. New local observations refresh automatically; missing windows stay hidden.
- **Validation:** Focused tests passed 17 tests plus 3 subtests. Full isolated suite passed 573 tests plus 49 subtests; task tests 25/25, generated-state check, diff check and fresh isolated installation/inert render passed. Independent scoped review passed: new observations replace waiting on the next tick; unchanged snapshots skip persistence; hidden widgets refresh; disabled sections and shutdown skip reads; local reads make no provider requests.
- **Done when:** A new valid local snapshot replaces waiting within the existing one-second display tick, without provider requests or repeated persistence of unchanged snapshots.
- **Deployment:** Runtime commit `03a7e038637bebe36fb38a6f2c400e38cda3bbe1` pushed; Python/install CI `41631457702` and repository guards `41631457664` passed. Existing user service restarted November 3 at 05:56:54 CT, active/running with zero automatic restarts. Native 340x723 capture verified a visible weekly meter, absent five-hour meter hidden and `Claude Code cache · just now`; no waiting message. Private capture `/tmp/claude-quota-refresh-fixed.png` remains untracked. No new billing or Claude inference request.
