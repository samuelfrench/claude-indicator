"""llama.cpp server discovery and the Local AI section's llama rows (all I/O mocked)."""

import os
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests
from PySide6.QtWidgets import QApplication

import claude_widget
from claude_widget import (
    LlamaOnDemand,
    LlamaServer,
    LlamaServersSnapshot,
    LocalAISection,
    OllamaFetchWorker,
    OllamaStatus,
    SystemMetrics,
    llama_activity_text,
    parse_llama_journal,
    parse_ss_rows,
    read_llama_servers,
    read_llama_units,
)

APP = QApplication.instance() or QApplication([])

JOURNAL = """\
1795468300.70 host qwen-server[1376056]: 2.03.576.723 I srv  server_run_i: model loaded
1795468301.23 host qwen-server[1376056]: 2.04.101.009 I slot launch_slot_: id  0 | task 0 | processing task, is_child = 0
1795468400.00 host qwen-server[999]: I slot print_timing: id  0 | task 0 | prompt processing, n_tokens =   2048, progress = 0.50, t = 1.00 s / 99.00 tokens per second
1795468450.00 host qwen-server[1376056]: I slot print_timing: id  0 | task 0 | prompt processing, n_tokens =   2048, progress = 0.01, t = 163.38 s / 12.54 tokens per second
1795468900.00 host qwen-server[1376056]: I slot print_timing: id  0 | task 0 | prompt processing, n_tokens =  40960, progress = 0.20, t = 900.00 s / 45.51 tokens per second
1795469000.00 host qwen-server[1376056]: I slot print_timing: id  0 | task 7 | prompt eval time =  1000.00 ms /   350 tokens (    2.86 ms per token,   350.00 tokens per second)
1795469000.10 host qwen-server[1376056]: I slot print_timing: id  0 | task 7 |        eval time =   33297.93 ms /   712 tokens (   46.83 ms per token,    21.35 tokens per second)
1795469000.20 host qwen-server[1376056]: I slot      release: id  0 | task 7 | stop processing: n_tokens = 185738, truncated = 0
"""

SS = """\
LISTEN 0 64 127.0.0.1:4790 0.0.0.0:* users:(("systemd",pid=4279,fd=40))
LISTEN 0 512 127.0.0.1:4791 0.0.0.0:* users:(("llama-server",pid=1376056,fd=5))
LISTEN 0 64 127.0.0.1:4792 0.0.0.0:* users:(("systemd",pid=4279,fd=41))
ESTAB 0 0 127.0.0.1:4791 127.0.0.1:52420 users:(("llama-server",pid=1376056,fd=17))
ESTAB 0 0 127.0.0.1:52420 127.0.0.1:4791 users:(("systemd-socket-",pid=1489342,fd=11))
ESTAB 0 0 127.0.0.1:39616 127.0.0.1:4790 users:(("opencode.exe",pid=967371,fd=32))
ESTAB 0 0 127.0.0.1:4790 127.0.0.1:39616 users:(("systemd-socket-",pid=1489342,fd=10))
ESTAB 0 0 [::1]:40000 [::1]:443 users:(("firefox",pid=55,fd=3))
"""


def _stat_line(pid: int, comm: str, ppid: int, start_ticks: int) -> str:
    fields = ["S", str(ppid)] + ["0"] * 17 + [str(start_ticks)] + ["0"] * 10
    return f"{pid} ({comm}) " + " ".join(fields) + "\n"


def _write_unit(unit_dir: Path, name: str, text: str) -> None:
    (unit_dir / name).write_text(text)


def _make_units(unit_dir: Path) -> None:
    unit_dir.mkdir()
    _write_unit(unit_dir, "llama-qwen.service", (
        "[Service]\n"
        "ExecStartPre=/home/u/.local/bin/gpu-evict-ollama\n"
        "ExecStart=/opt/llama.cpp/bin/llama-server -m /models/Qwen-00001-of-00004.gguf \\\n"
        "  --alias qwen3.8-flash-next --host 127.0.0.1 --port 4791 -c 262144\n"
    ))
    _write_unit(unit_dir, "llama-qwen-proxy.service", (
        "[Service]\nExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=15min 127.0.0.1:4791\n"
    ))
    _write_unit(unit_dir, "llama-qwen-proxy.socket", "[Socket]\nListenStream=127.0.0.1:4790\n")
    _write_unit(unit_dir, "llama-small.service", (
        "[Service]\nExecStart=/opt/llama-server --model /models/small.gguf --port 4793\n"
    ))
    _write_unit(unit_dir, "llama-small-proxy.service", (
        "[Service]\nExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=5min 127.0.0.1:4793\n"
    ))
    _write_unit(unit_dir, "llama-small-proxy.socket", "[Socket]\nListenStream=4792\n")
    # Backups and non-.service files are ignored.
    _write_unit(unit_dir, "llama-qwen.service.bak-20261115", "ExecStart=/opt/llama-server --port 9999\n")


def _make_proc(proc_dir: Path) -> None:
    proc_dir.mkdir()
    (proc_dir / "stat").write_text("cpu 1 2 3\nbtime 1795000000\n")

    def add(pid, comm, argv, ppid=1, start=100, status="", cgroup=""):
        entry = proc_dir / str(pid)
        entry.mkdir()
        (entry / "comm").write_text(comm + "\n")
        (entry / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")
        (entry / "stat").write_text(_stat_line(pid, comm, ppid, start))
        (entry / "status").write_text(status)
        (entry / "cgroup").write_text(cgroup)

    add(4279, "systemd", ["/usr/lib/systemd/systemd", "--user"])
    add(
        1376056, "llama-server",
        ["/opt/llama.cpp/bin/llama-server", "-m", "/models/Qwen-00001-of-00004.gguf", "--mmproj",
         "/models/mmproj.gguf", "--alias", "qwen3.8-flash-next", "--host", "127.0.0.1", "--port", "4791",
         "-c", "262144"],
        ppid=4279, start=4680000,
        status="Name:\tllama-server\nVmRSS:\t 12582912 kB\n",
        cgroup="0::/user.slice/user-1000.slice/user@1000.service/app.slice/llama-qwen.service\n",
    )
    add(4434, "ollama", ["/usr/local/bin/ollama", "serve"])
    # Ollama's bundled runner is reported by /api/ps, not as a llama.cpp server.
    add(5000, "llama-server", ["/usr/lib/ollama/llama-server", "--port", "33333"], ppid=4434)
    add(6000, "python3", ["/usr/bin/python3", "/srv/ComfyUI/main.py", "--listen"])


def _response(status_code=200, payload=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


MODELS = {
    "data": [{
        "id": "qwen3.8-flash-next",
        "architecture": {"input_modalities": ["text", "image"]},
        "meta": {"n_params": 176943899520, "size": 89453923840, "ftype": "Q3_K - Medium", "n_ctx": 262144},
    }]
}
SLOTS_PREFILL = [{
    "id": 0, "n_ctx": 262144, "is_processing": True, "id_task": 0,
    "n_prompt_tokens": 40960, "n_prompt_tokens_processed": 38912,
    "next_token": [{"has_next_token": True, "n_decoded": 0}],
}]


def _fake_get(slots):
    def get(url, timeout):
        assert url.startswith("http://127.0.0.1:4791/"), url
        assert timeout == claude_widget.LLAMA_HTTP_TIMEOUT
        path = url.split(":4791", 1)[1]
        return {
            "/health": _response(200, {"status": "ok"}),
            "/v1/models": _response(200, MODELS),
            "/slots": _response(200, slots),
        }[path]
    return get


def _fake_run(commands):
    def run(cmd):
        commands.append(cmd)
        if cmd[0] == "nvidia-smi":
            return "1376056, 23020\n6000, 6144\n"
        if cmd[0] == "ss":
            return SS
        if cmd[0] == "journalctl":
            return JOURNAL
        raise AssertionError(cmd)
    return run


class LlamaParsingTests(TestCase):
    def test_journal_parser_scopes_to_pid_and_reads_timing_only(self):
        stats = parse_llama_journal(JOURNAL, 1376056)
        self.assertEqual(stats.prefill[0], (40960, 0.20, 45.51))
        self.assertEqual(stats.last_prompt_tps, 350.0)
        self.assertEqual(stats.last_gen_tps, 21.35)
        self.assertEqual(stats.last_context_tokens, 185738)
        self.assertEqual(stats.last_release_at, 1795469000.20)
        self.assertEqual(parse_llama_journal(JOURNAL, 999).prefill[0], (2048, 0.5, 99.0))

    def test_ss_rows_parse_ports_and_processes(self):
        rows = parse_ss_rows(SS)
        self.assertEqual(rows[0], ("LISTEN", 4790, 0, [("systemd", 4279)]))
        self.assertEqual(rows[5], ("ESTAB", 39616, 4790, [("opencode.exe", 967371)]))
        self.assertEqual(rows[7][1:3], (40000, 443))

    def test_units_map_backend_port_to_socket_front_and_idle_exit(self):
        tmp = Path(self._tmp())
        _make_units(tmp / "units")
        backends, fronts = read_llama_units(tmp / "units")
        self.assertEqual(
            [(unit.unit, unit.port, unit.alias, unit.model_file) for unit in backends],
            [
                ("llama-qwen.service", 4791, "qwen3.8-flash-next", "Qwen-00001-of-00004.gguf"),
                ("llama-small.service", 4793, "", "small.gguf"),
            ],
        )
        self.assertEqual(fronts, {4791: (4790, 900), 4793: (4792, 300)})
        self.assertEqual(read_llama_units(tmp / "missing"), ([], {}))

    def test_units_read_options_from_a_wrapper_script(self):
        tmp = Path(self._tmp())
        units = tmp / "units"
        units.mkdir()
        bin_dir = tmp / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "qwen-server").write_text(
            "#!/usr/bin/env bash\n"
            "# Wrapper: llama-server with model options\n"
            'MODEL_DIR="$HOME/models"\n'
            "args=(\n"
            '  -m "$MODEL_DIR/Qwen-00001-of-00004.gguf"\n'
            "  --alias qwen3.8-flash-next --host 127.0.0.1 --port 4791\n"
            '  --slot-save-path "$SLOT_DIR/"\n'
            ")\n"
            'exec "$LLAMA_DIR/bin/llama-server" "${args[@]}" "$@"\n'
        )
        (bin_dir / "not-a-model").write_text("#!/bin/sh\nexec sleep 1 --port 9\n")
        (bin_dir / "watchdog").write_text('#!/usr/bin/env python3\n# restarts llama-server when wedged\nprint("llama-server ok")\n')
        _write_unit(units, "llama-qwen.service", (
            "[Service]\nExecStartPre=%h/.local/bin/gpu-evict-ollama\nExecStart=%h/.local/bin/qwen-server\n"
        ))
        _write_unit(units, "other.service", "[Service]\nExecStart=%h/.local/bin/not-a-model\n")
        _write_unit(units, "watchdog.service", "[Service]\nExecStart=%h/.local/bin/watchdog\n")
        _write_unit(units, "llama-qwen-proxy.service", (
            "[Service]\nExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=15min 127.0.0.1:4791\n"
        ))
        _write_unit(units, "llama-qwen-proxy.socket", "[Socket]\nListenStream=127.0.0.1:4790\n")

        with patch.object(Path, "home", return_value=tmp / "home"):
            backends, fronts = read_llama_units(units)

        self.assertEqual(
            [(unit.unit, unit.port, unit.alias, unit.model_file) for unit in backends],
            [("llama-qwen.service", 4791, "qwen3.8-flash-next", "Qwen-00001-of-00004.gguf")],
        )
        self.assertEqual(fronts, {4791: (4790, 900)})

    def _tmp(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name


class ReadLlamaServersTests(TestCase):
    def setUp(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        _make_proc(self.root / "proc")
        _make_units(self.root / "units")

    def _read(self, slots):
        commands = []
        with patch.object(claude_widget.requests, "get", side_effect=_fake_get(slots)):
            snapshot = read_llama_servers(self.root / "proc", self.root / "units", run=_fake_run(commands))
        return snapshot, commands

    def test_socket_activated_server_reports_prefill_progress_clients_and_resources(self):
        snapshot, commands = self._read(SLOTS_PREFILL)

        self.assertEqual([server.pid for server in snapshot.servers], [1376056])
        server = snapshot.servers[0]
        self.assertEqual(server.state, "prefill")
        self.assertEqual((server.port, server.front_port, server.idle_exit_s), (4791, 4790, 900))
        self.assertEqual(server.unit, "llama-qwen.service")
        self.assertEqual(server.alias, "qwen3.8-flash-next")
        self.assertEqual(server.n_params, 176943899520)
        self.assertEqual(server.ftype, "Q3_K - Medium")
        self.assertTrue(server.vision)
        self.assertEqual((server.slots_total, server.slots_busy, server.task_id), (1, 1, 0))
        # The log is fresher than nothing but older than /slots; keep the larger count.
        self.assertEqual(server.prompt_done, 40960)
        self.assertEqual(server.prompt_total_est, 204800)
        self.assertEqual(server.prompt_tps, 45.51)
        self.assertAlmostEqual(server.prefill_eta_seconds(), (204800 - 40960) / 45.51)
        self.assertEqual(server.last_gen_tps, 21.35)
        self.assertEqual(server.vram_bytes, 23020 * 1024 * 1024)
        self.assertEqual(server.rss_bytes, 12582912 * 1024)
        self.assertAlmostEqual(server.started_at, 1795000000 + 4680000 / os.sysconf("SC_CLK_TCK"))
        self.assertEqual(server.clients, ["opencode (967371)"])
        self.assertIn(
            ["journalctl", "--user", "-u", "llama-qwen.service", "-n", "300", "-o", "short-unix", "--no-pager", "-q"],
            commands,
        )

        self.assertEqual(
            [(unit.unit, unit.front_port, unit.idle_exit_s) for unit in snapshot.on_demand],
            [("llama-small.service", 4792, 300)],
        )
        self.assertEqual(
            [(process.name, process.pid) for process in snapshot.gpu_processes],
            [("llama-server", 1376056), ("ComfyUI", 6000)],
        )

    def test_idle_generating_loading_and_unreachable_states(self):
        idle = [dict(SLOTS_PREFILL[0], is_processing=False)]
        self.assertEqual(self._read(idle)[0].servers[0].state, "idle")

        generating = [dict(SLOTS_PREFILL[0], next_token=[{"n_decoded": 512}])]
        server = self._read(generating)[0].servers[0]
        self.assertEqual((server.state, server.decoded, server.prompt_total_est), ("generating", 512, 0))

        with patch.object(claude_widget.requests, "get", return_value=_response(503, {})):
            server = read_llama_servers(self.root / "proc", self.root / "units", run=_fake_run([])).servers[0]
        self.assertEqual(server.state, "loading")

        with patch.object(claude_widget.requests, "get", side_effect=requests.ConnectionError("refused")):
            server = read_llama_servers(self.root / "proc", self.root / "units", run=_fake_run([])).servers[0]
        self.assertEqual((server.state, server.error), ("unreachable", "ConnectionError"))

    def test_slots_disabled_leaves_activity_unknown(self):
        def get(url, timeout):
            if url.endswith("/slots"):
                return _response(501, {"error": {"code": 501}})
            return _fake_get(SLOTS_PREFILL)(url, timeout)

        with patch.object(claude_widget.requests, "get", side_effect=get):
            server = read_llama_servers(self.root / "proc", self.root / "units", run=_fake_run([])).servers[0]
        self.assertEqual(server.state, "running")
        self.assertIn("activity unknown", llama_activity_text(server, time.time()))

    def test_nothing_running_skips_socket_scan(self):
        empty_proc = self.root / "empty-proc"
        empty_proc.mkdir()
        commands = []
        snapshot = read_llama_servers(empty_proc, self.root / "missing-units", run=_fake_run(commands))
        self.assertEqual(snapshot.servers, [])
        self.assertEqual([cmd[0] for cmd in commands], ["nvidia-smi"])


class LocalAISectionLlamaTests(TestCase):
    def _server(self, **overrides):
        values = dict(
            pid=10, port=4791, alias="qwen3.8-flash-next", state="prefill", n_params=176943899520,
            size_bytes=89453923840, ftype="Q3_K - Medium", n_ctx=262144, vision=True,
            prompt_done=40960, prompt_total_est=204800, prompt_progress=0.2, prompt_tps=45.5,
            vram_bytes=22 * 1024 ** 3, rss_bytes=12 * 1024 ** 3, started_at=time.time() - 600,
            front_port=4790, idle_exit_s=900, clients=["opencode (967371)"], unit="llama-qwen.service",
            model_file="Qwen-00001-of-00004.gguf", slots_total=1, slots_busy=1, task_id=0,
        )
        values.update(overrides)
        return LlamaServer(**values)

    def test_llama_server_replaces_no_models_loaded_and_names_the_model(self):
        section = LocalAISection()
        section.setFixedWidth(340)
        section.set_ollama(OllamaStatus(running=True, version="0.12"), [], 14)
        section.set_gpu(SystemMetrics(gpu_available=True, gpu_pct=3, gpu_mem_used_gb=22.5, gpu_mem_total_gb=24))
        before_text, _color = section.summary_text()
        self.assertEqual(before_text, "NO MODEL LOADED  ·  GPU 3%")

        section.set_expanded(True)
        empty_height = section.height()
        snapshot = LlamaServersSnapshot(
            servers=[self._server()],
            on_demand=[LlamaOnDemand(unit="llama-small.service", model_file="small.gguf", front_port=4792)],
            gpu_processes=[claude_widget.GpuProcess(pid=10, name="llama-server", vram_bytes=22 * 1024 ** 3)],
        )
        section.set_llama(snapshot)

        self.assertEqual(section.summary_text()[0], "QWEN3.8 PREFILL 20%  ·  GPU 3%")
        # Placeholder row (28) replaced by header, one server block, one on-demand line, VRAM holders.
        self.assertEqual(section.height(), empty_height - 28 + 16 + 64 + 14 + 14)
        tooltip = section.toolTip()
        self.assertIn("llama.cpp qwen3.8-flash-next (PID 10, unit llama-qwen.service) on 127.0.0.1:4790→:4791", tooltip)
        self.assertIn("PREFILL 41.0K/~204.8K tok · 20% · 45.5 t/s · ETA ~60m", tooltip)
        self.assertIn("proxy exits after 15m idle", tooltip)
        self.assertIn("small.gguf: not loaded; starts on demand at 127.0.0.1:4792", tooltip)
        self.assertIn("VRAM 22.0 GB held by llama-server (PID 10)", tooltip)
        self.assertFalse(section.grab().isNull())

    def test_generation_rate_comes_from_successive_decode_samples(self):
        section = LocalAISection()
        with patch.object(claude_widget.time, "monotonic", return_value=100.0):
            section.set_llama(LlamaServersSnapshot(servers=[self._server(state="generating", decoded=100)]))
        with patch.object(claude_widget.time, "monotonic", return_value=110.0):
            section.set_llama(LlamaServersSnapshot(servers=[self._server(state="generating", decoded=313)]))
        server = section._llama.servers[0]
        self.assertAlmostEqual(server.live_gen_tps, 21.3)
        self.assertIn("GENERATING 313 tok · 21.3 t/s", section.toolTip())
        self.assertEqual(section.summary_text()[0].split("  ·  ")[0], "QWEN3.8 GENERATING")

    def test_idle_text_counts_down_to_socket_proxy_unload(self):
        now = 10_000.0
        server = self._server(state="idle", last_release_at=now - 240)
        self.assertEqual(llama_activity_text(server, now), "IDLE 4m · unloads in ~11m")
        self.assertEqual(llama_activity_text(self._server(state="idle", last_release_at=now - 1000), now),
                         "IDLE 16m · unload pending")
        unproxied = self._server(state="idle", front_port=0, last_release_at=0.0, started_at=now - 30)
        self.assertEqual(llama_activity_text(unproxied, now), "IDLE 30s")
        self.assertEqual(llama_activity_text(self._server(state="unreachable", error="ReadTimeout"), now),
                         "NOT RESPONDING (ReadTimeout)")


class OllamaWorkerLlamaTests(TestCase):
    def test_worker_reports_llama_servers_even_when_ollama_is_down(self):
        snapshot = LlamaServersSnapshot(servers=[LlamaServer(pid=1, state="idle")])
        worker = OllamaFetchWorker(llama_reader=lambda: snapshot)
        received = []
        worker.result.connect(lambda *args: received.append(args))
        with patch.object(claude_widget.requests, "get", side_effect=requests.ConnectionError("down")):
            worker.run()
        status, models, available, llama = received[0]
        self.assertFalse(status.running)
        self.assertEqual((models, available), ([], 0))
        self.assertIs(llama, snapshot)

    def test_discovery_failure_is_logged_and_keeps_ollama_result(self):
        def broken():
            raise RuntimeError("boom")

        worker = OllamaFetchWorker(llama_reader=broken)
        received = []
        worker.result.connect(lambda *args: received.append(args))
        with patch.object(claude_widget.requests, "get", side_effect=requests.ConnectionError("down")), \
                patch.object(claude_widget, "log_line") as log:
            worker.run()
        self.assertEqual(received[0][3].servers, [])
        log.assert_called_once_with("llama.cpp discovery failed: RuntimeError: boom")
