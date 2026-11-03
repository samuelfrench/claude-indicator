---
title: "Refresh Claude local quota as soon as it arrives"
status: now
area: product
due: null
updated: 2026-11-03
owner: agent
brief: "Replace the five-minute local-feed delay with pickup on the existing one-second timer."
refs: []
test: null
---
- **What:** Pick up changed local quota data promptly, keeping provider polling unchanged and preserving missing-window semantics.
- **Why:** The native widget last read an unavailable feed at 05:52:14 CT; a valid weekly-only observation arrived at 05:52:27, but the next automatic fetch was scheduled for 05:56:12. A direct local reader succeeds while the widget still displays Waiting for Claude Code quota. This is update latency, not missing OAuth authentication.
- **Next:** Push tested implementation, wait for both CI workflows and restart the existing service. Verify the native weekly meter and cached-age footer.
- **Validation:** Focused tests passed 17 tests plus 3 subtests. Full isolated suite passed 573 tests plus 49 subtests; task tests 25/25, generated-state check, diff check and fresh isolated installation/inert render passed. Independent scoped review passed: new observations replace waiting on the next tick; unchanged snapshots skip persistence; hidden widgets refresh; disabled sections and shutdown skip reads; local reads make no provider requests.
- **Done when:** A new valid local snapshot replaces waiting within the existing one-second display tick, without provider requests or repeated persistence of unchanged snapshots.
