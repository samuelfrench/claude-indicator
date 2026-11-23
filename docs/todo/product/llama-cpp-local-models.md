---
title: "Local AI shows llama.cpp servers, not only Ollama"
status: now
area: product
due: null
updated: 2026-11-23
owner: agent
brief: "Local AI said 'No models loaded' while a socket-activated llama-server held 22.5 GB VRAM; it now discovers llama-server processes and on-demand units."
refs: ["claude_widget.py", "tests/test_llama_servers.py", "tests/conftest.py", "README.md", "docs/beta/privacy-audit.md"]
test: null
---
- **What:** On 2026-11-23 15:19 CT the Local AI section read `OLLAMA ▸ RUNNING` / `No models loaded` because it queried only Ollama (`/api/ps` returned `{"models":[]}`). The real model was `llama-qwen38-flash-next.service`: llama.cpp `llama-server` PID 1376056, Qwen3.8-Flash-Next abliterated v2 UD-Q3_K_XL (176.9B params, 83.3 GB GGUF, ctx 262144, vision), 22.5 GB VRAM + ~40 GB RSS, socket-activated through `systemd-socket-proxyd` on 127.0.0.1:4790 -> :4791 with `--exit-idle-time=15min`. Its `ExecStartPre=gpu-evict-ollama` unloads Ollama first, so Ollama is always empty while it runs. Client: `opencode` PID 967371.
- **Fix:** `read_llama_servers()` (run by `OllamaFetchWorker` every 10 s, also when Ollama is down) finds `llama-server` processes in `/proc` (skipping Ollama's own runner), reads `/health`, `/v1/models`, `/slots`, maps socket proxies from user systemd unit files, parses the unit's journal timing lines for prefill progress / prompt and generation tokens/s, names connected clients from `ss -Htanp`, and lists per-process VRAM from `nvidia-smi --query-compute-apps`. Socket-activated units whose model is not loaded appear as on-demand. The section header is now `LOCAL AI ▸ <MODEL> <STATE> · GPU n%`; each server shows specs, activity (prefill tokens/~total, %, t/s, ETA; generating tokens and live t/s from successive `/slots` samples; idle time and the socket-proxy unload countdown), VRAM/RAM/uptime/PID and client plus last-request stats. A `VRAM held by` line covers models run any other way (ComfyUI, Python).
- **Test isolation fix:** 8 `ClaudeUsageClient.fetch` tests failed locally on unmodified master (`'statusline' != 'ratelimit_headers'` etc.) because `read_claude_statusline_usage` reads the owner's real `~/.claude/settings.json`; CI isolates HOME, local runs did not. `tests/conftest.py` now sets an isolated HOME per test.
- **Validation (pre-deploy):** `tests/test_llama_servers.py` 12 tests (journal/ss/unit parsing, fake `/proc` end to end, states, section height/tooltip/summary, decode-rate sampling, worker emits llama data when Ollama is down and logs discovery failures). Full suite `602 passed, 51 subtests passed` (master baseline locally: `582 passed, 8 failed`). Live reader run took 0.18 s and reported prefill 41K/~186K tokens at 43.6 t/s.
- **Next:** Push, green CI, restart `claude-indicator.service`, verify the live widget.
