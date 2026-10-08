# Task files and generated TODO

`TODO.md` and `docs/todo/index.json` are generated from `docs/todo/<area>/<slug>.md`. Edit the task source, run `node scripts/todo/build.mjs`, and commit the source plus both outputs together. Never hand-edit the generated files. Finished task files move to `docs/todo/done/<area>/`; older completed detail belongs in `TODO-archive.md` with an anchor listed in `refs`.

Each task starts with YAML frontmatter containing `title`, `status`, `area`, `due` (date or null), `updated` (date), `owner` (`agent` or `sam`), `brief`, `refs` (list), and `test` (required for known failures). Statuses are `now`, `waiting-sam`, `scheduled`, `next`, `idea`, `known-failure`, and `done`; scheduled items require a due date. Areas are listed in `scripts/todo/lib.mjs`.

Keep What / Why / Next summary, exact evidence, reproduction commands and done criteria in the body. Update the relevant task in the same working beat whenever scope, status, results or blockers change. Preserve deferred defects, rejected ideas with the measured reason, interruption points and follow-ups. Treat old release notes as historical evidence and verify current state before acting.

- Find current work: `node scripts/todo/query.mjs --status now,waiting-sam`.
- Query a date: `node scripts/todo/query.mjs --due-before 2026-10-15`.
- Find failures: `node scripts/todo/query.mjs --test widget`.
- Search all tasks: `node scripts/todo/query.mjs --grep beta --all`.
- Validate: `node --test scripts/todo/__tests__/todo.test.mjs` and `node scripts/todo/build.mjs --check`.

## Known non-blocking failures — check here BEFORE diagnosing a red suite

Record the exact failing command/test in `test`, observed message, trigger, evidence distinguishing historical behavior from regression, and the deferred real fix. The generated TODO retains this stable heading. Repository guards run both the task tests and drift check; no deployment workflow exists in this desktop application repository.
