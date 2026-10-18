---
title: "Fresh-install verifier copies uv standalone Python incorrectly"
status: known-failure
area: infra
due: null
updated: 2026-10-18
owner: agent
brief: "Local uv Python3.10 copied-venv bootstrap fails before install; symlink bootstrap and unmodified hosted verifier pass."
refs: ["scripts/verify_install.py", "docs/todo/done/product/minimize-tray-usage.md"]
test: "python scripts/verify_install.py under uv standalone Python3.10"
---
- **What:** `scripts/verify_install.py:113` uses `venv.EnvBuilder(with_pip=True)` with its default copied executable. With this host's uv standalone Python3.10.19, ensurepip exits1 before package installation because the copied interpreter searches `/install/lib/python3.10` and cannot import `encodings`.
- **Why:** The application/package itself is unaffected; the diagnostic install helper fails for that portable interpreter. October18 hosted Python3.10.22 runs the unmodified verifier successfully, and the same local verifier with only `EnvBuilder(symlinks=True)` passes8 installed modules, help/version and inert rendering. Preserve the distinction; do not describe the local adapted run as the unmodified gate.
- **Reproduce:** From the repo, create a task-owned temporary directory with `indicator_repro="$(mktemp -d /tmp/indicator-uv-verifier.XXXXXX)"`; run `uv venv --python 3.10 "$indicator_repro/venv"`, then `"$indicator_repro/venv/bin/python" scripts/verify_install.py`. No provider credentials or live app interactions are needed. Keep the failure output; remove only that task-owned temporary directory afterward.
- **Evidence:** Reproduced twice on October18; error `Could not find platform independent libraries <prefix>` followed by `ModuleNotFoundError: No module named 'encodings'`, ensurepip exit1. Local adapted receipt: `~/indicator-beta/minimize-tray-2026-10-18/install-compat-validation.json`; unmodified hosted success at source78f8448 run39145804950. The default Python3.13.9 local verifier passed before this portable-interpreter experiment.
- **Next / done:** In a separate bounded tooling task, support the portable interpreter bootstrap without weakening the smoke or isolation checks; require the unmodified helper to return0 on uv standalone Python3.10 plus normal hosted Python, with all8 modules, help/version and inert render proven. No runtime fix or additional app restart is needed for this deferred helper issue.
