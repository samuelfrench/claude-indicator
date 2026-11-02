---
title: Open Outreach Studio from the tray
status: now
area: product
due: null
updated: 2026-11-01
owner: agent
brief: "Implemented and reviewed; 554 tests plus 46 subtests, 25 TODO tests and fresh installation verifier pass. Awaiting CI and live service restart."
refs:
  - "../outreach-automation/README.md"
test: "QT_QPA_PLATFORM=offscreen python3 -m pytest -q"
---
Sam requested a tray link while centralizing all outreach in outreach-automation. Add Outreach Studio alongside Traffic Report, using QDesktopServices and existing launch-failure feedback. Preserve unrelated tray/configuration behavior. Verify action URL and both menu instances, required repo gates and green CI, then deploy existing user service and inspect runtime menu. No mail sends are part of this change.

2026-11-01: independent scoped review found no issues. Existing suite and fresh isolated package installation passed; action test triggers the actual menu item and checks exact local URL. App repository CI 41371354742 passed and app service is being installed.
