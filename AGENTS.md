# Project Codex Loader

Before substantial work, read `/home/sam/.codex/memories/MEMORY.md`.

Then read local project context when present:
- `CLAUDE.md`
- `TODO.md`
- `/home/sam/.codex/memories/project-context-index.md`

For deeper history, follow the matching Claude memory path listed in `/home/sam/.codex/memories/project-context-index.md`.
Do not reveal secrets from historical memory or export files.

## Repository task tracking

`TODO.md` and `docs/todo/index.json` are generated. Read `TODO.md`, then edit the linked source under `docs/todo/<area>/<slug>.md`; never hand-edit the generated files. Update the source in the same working beat as a status, scope, result or blocker change. Run `node scripts/todo/build.mjs` and commit source, TODO and index together. Query with `node scripts/todo/query.mjs --status now,waiting-sam` or `--grep <text> --all`. Before pushing, run `node --test scripts/todo/__tests__/todo.test.mjs` and `node scripts/todo/build.mjs --check`. Rules and archival conventions are in `docs/todo/README.md`.
