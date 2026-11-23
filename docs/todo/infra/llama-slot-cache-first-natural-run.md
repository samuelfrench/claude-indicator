---
title: "Confirm the first natural llama slot cache save and restore"
status: next
area: infra
due: null
updated: 2026-11-23
owner: agent
brief: "llama-slot-cache is installed but only a CPU test model proved it; confirm the live Qwen unit saves on its next unload and restores on the following load."
refs: ["docs/todo/done/product/llama-cpp-local-models.md"]
test: null
---
- **What:** `llama-qwen38-flash-next.service` saves slot 0 on stop and restores it on start through `~/.local/bin/llama-slot-cache` (installed 2026-11-23 ~16:00 CT, details in the linked task). The instance running at install (PID 1376056) lacks `--slot-save-path`, so its stop will log `kept previous cache; nothing saved: ... does not support slots action`; that is expected.
- **Check:** `journalctl --user -u llama-qwen38-flash-next.service -g llama-slot-cache --no-pager` and `ls -la ~/.cache/llama-slots/qwen38-flash-next/`. Done when one stop logs `saved N tokens, B bytes, T ms` (expect N in the 100K-250K range, a few GB, save under 45 s) and the next start logs `restored N tokens`, and that start's first `prompt processing` line shows `n_prompt_tokens_cache`/progress starting near N instead of 0 (Local AI row: PREFILL from near the full context).
- **If the save exceeds 45 s or the stop hits 90 s:** raise the curl cap in `llama-slot-cache` and `TimeoutStopSec`, keeping the cap under the 60 s `systemctl stop` timeout in `~/.config/opencode/lib/gpu-model-swap.mjs` (or raise that too in codex-local-config).
- **Rollback:** `cp ~/.config/systemd/user/llama-qwen38-flash-next.service.bak-20261123 ~/.config/systemd/user/llama-qwen38-flash-next.service && cp ~/.local/bin/qwen38-flash-next-server.bak-20261123 ~/.local/bin/qwen38-flash-next-server && systemctl --user daemon-reload` (takes effect on the next start).
