---
title: Open Outreach Studio from the tray
status: done
area: product
due: null
updated: 2026-11-01
owner: agent
brief: "Deployed 35980eb after both green CI runs; live Claude and Codex DBus tray menus expose enabled Outreach Studio link; local app health verified."
refs:
  - "../outreach-automation/README.md"
test: "QT_QPA_PLATFORM=offscreen python3 -m pytest -q"
---
Sam requested a tray link while centralizing all outreach in outreach-automation. Add Outreach Studio alongside Traffic Report, using QDesktopServices and existing launch-failure feedback. Preserve unrelated tray/configuration behavior. Verify action URL and both menu instances, required repo gates and green CI, then deploy existing user service and inspect runtime menu. No mail sends are part of this change.

2026-11-01: independent scoped review found no issues. Existing suite and fresh isolated package installation passed; action test triggers the actual menu item and checks exact local URL. App repository CI 41371354742 passed and app service is being installed.

Deployment proof: master35980eb75db71b227238574ba8c88e04bb803a54, Python CI41371479414 and guard CI41371479339 success. Existing claude-indicator.service restarted, active PID3350356/NRestarts0. org.kde.StatusNotifierWatcher registered both new tray instances; com.canonical.dbusmenu.GetLayout on :1.85990 and :1.85991 /MenuBar returns enabled+visible Outreach Studio (action27) after Traffic Report. QAction test confirms exact http://127.0.0.1:4740/ URL; app /api/health reports e27faf07b621f91c1701aaf5332a8496a676dda8. No browser launch or mail send during verification.
