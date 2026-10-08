---
title: "Legacy unrelated source-zone hold"
status: waiting-sam
area: infra
due: null
updated: 2026-10-07
owner: sam
brief: "Preserved during migration; privacy review must remove unrelated infrastructure notes from this product repository."
refs: []
test: null
---
- **What:** An unrelated infrastructure task was present in the original TODO.
- **Why:** This migration preserves every source line for audit; beta privacy work owns removal.
- **Next:** Root privacy reviewer archives this outside the product repository before pushing. No infrastructure action is authorized.

- [ ] Delete the 16 Route 53 source zones only after `2026-07-20T15:18:57.201000Z`, each rolling stale-cache clock, a 13-round/one-hour resolver clean window, and both full delayed gates pass.

