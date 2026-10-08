# Project operating context

Before substantial work, read `CLAUDE.md`, generated `TODO.md` and the linked task source. Use injected memory and topic-relevant shared project memory when available; do not export private history or credentials into this public repository. Current live state and evidence outrank historical notes.

`TODO.md` and `docs/todo/index.json` are generated. Edit sources under `docs/todo/<area>/<slug>.md`, run `node scripts/todo/build.mjs`, and commit source plus both outputs together. Update sources in the same working beat as status, scope, evidence or blocker changes. Query with `node scripts/todo/query.mjs --status now,waiting-sam` or `--grep <text> --all`; validate with `node --test scripts/todo/__tests__/todo.test.mjs` and `node scripts/todo/build.mjs --check`. Rules and archive conventions are in `docs/todo/README.md`.

Use one implementation agent at a time, then independent task review and scoped fixes. Preserve unrelated work. Do not interact with the user's running widget, other projects or terminal sessions as part of beta installation tests. See the active task for no-launch/no-posting and provider-call boundaries.
