---
title: "Migrate TODO to generated task files"
status: done
area: process
due: null
updated: 2026-10-07
owner: agent
brief: "Original 70-line TODO preserved; generated tasks and CI guards replace manual edits."
refs: ["docs/todo/migration-2026-10-07.md", "scripts/todo/migrate-monolith.mjs"]
test: null
---
- **What:** Convert hand-maintained TODO to task files, generated index and dedicated guards.
- **Why:** Continuous checkpoints must remain reproducible and individually queryable.
- **Next:** Edit task sources, run `node scripts/todo/build.mjs`, and commit task, TODO and index together.
- **Result:** 25 task-workflow tests passed, drift check passed (8 tasks), all 53 original non-empty lines retained with 0 missing, all 4 original open checkboxes retained with 0 missing.
- **Validation:** `node --test scripts/todo/__tests__/todo.test.mjs`; `node scripts/todo/build.mjs --check`; migration verifier and open-checkbox comparison below.

