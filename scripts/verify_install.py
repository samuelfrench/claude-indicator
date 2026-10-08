#!/usr/bin/env python3
"""Verify a fresh install without reading the user's state or contacting providers."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

SMOKE = r"""
import importlib
import json
import platform
import os
from importlib.metadata import version
import subprocess
from contextlib import ExitStack
from unittest.mock import patch
import requests
import urllib.request

modules = ["indicator_cli", "claude_widget", "smart_todos", "smart_todo_workflow",
           "terminal_recovery", "terminal_recovery_ui", "widget_runtime", "cursor_usage"]
for name in modules:
    installed = importlib.import_module(name)
    assert "site-packages" in installed.__file__, installed.__file__

from PySide6.QtWidgets import QApplication
import claude_widget as widget_module

methods = ["_setup_tray_icon", "_setup_timers", "_fetch_usage", "_fetch_deploys",
           "_fetch_runners", "_fetch_task_loops", "_fetch_task_groups", "_fetch_cron_jobs",
           "_fetch_ollama", "_fetch_comfyui", "_update_system_metrics", "_refresh_codex_usage",
           "_refresh_deepseek_usage", "_refresh_minimax_usage", "_refresh_opencode_go_usage",
           "_refresh_grok_usage", "_refresh_cursor_usage", "_refresh_opencode_usage", "_refresh_terminal_sessions"]
def blocked(*args, **kwargs):
    raise AssertionError("Install smoke cannot use HTTP or subprocesses")
def inert(*args, **kwargs):
    return None
app = QApplication([])
with ExitStack() as patches:
    patches.enter_context(patch.object(requests.sessions.Session, "request", blocked))
    patches.enter_context(patch.object(urllib.request, "urlopen", blocked))
    patches.enter_context(patch.object(subprocess, "Popen", blocked))
    patches.enter_context(patch.object(widget_module, "SystemMetricsReader", lambda: None))
    for name in methods:
        patches.enter_context(patch.object(widget_module.ClaudeWidget, name, inert))
    widget = widget_module.ClaudeWidget()
    widget.show()
    app.processEvents()
    image = widget.grab().toImage()
    assert widget.width() == 340 and image.width() == 340 and image.height() > 0
    assert not widget._cursor_row.isHidden()
    assert "Not connected" in widget._cursor_row.summary_text()
    assert widget._cursor_row.bot_text() == "Grok Bot   — · meter unavailable"
    assert widget._cursor_row is not widget._grok_row
    image_path = os.environ.get("INDICATOR_SMOKE_IMAGE")
    if image_path:
        assert image.save(image_path)
    result = {"modules": modules, "platform": app.platformName(),
              "render_width": image.width(), "render_height": image.height(),
              "provider_http": "blocked", "subprocesses": "blocked",
              "python": platform.python_version(), "pyside6": version("PySide6"),
              "all_modules_from_installed_package": True,
              "cursor": widget._cursor_row.summary_text(),
              "cursor_grok_bot": widget._cursor_row.bot_text()}
    widget.shutdown()
    widget.close()
    app.processEvents()
print(json.dumps(result))
"""


def isolated_env(home):
    env = dict(os.environ)
    sensitive_prefixes = ("ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_", "GROK_", "CURSOR_", "XAI_",
                          "DEEPSEEK_", "MINIMAX_", "OPENCODE_", "GH_", "GITHUB_")
    for key in tuple(env):
        if key.startswith(sensitive_prefixes) or key in {
            "PYTHONPATH", "PYTHONHOME", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
            "NOTIFY_SOCKET", "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK",
        }:
            env.pop(key, None)
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_RUNTIME_DIR": str(home / "runtime"),
                "CODEX_HOME": str(home / ".codex"), "GROK_HOME": str(home / ".grok"),
                "QT_QPA_PLATFORM": "offscreen", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    (home / "runtime").mkdir(mode=0o700)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]),
                        help="Local source or a pip Git URL to install")
    parser.add_argument("--report", type=Path, help="Write non-sensitive JSON evidence")
    parser.add_argument("--image", type=Path, help="Save the inert offscreen widget image")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="indicator-install-") as tmp:
        work = Path(tmp)
        home = work / "home"
        home.mkdir(mode=0o700)
        env = isolated_env(home)
        if args.image:
            env["INDICATOR_SMOKE_IMAGE"] = str(args.image.resolve())
        install_env = work / "venv"
        venv.EnvBuilder(with_pip=True).create(install_env)
        python = install_env / "bin/python"
        command = install_env / "bin/claude-indicator"
        subprocess.run([str(python), "-m", "pip", "install", args.source],
                       cwd=work, env=env, check=True, stdout=subprocess.DEVNULL)
        results = {}
        for flag in ("--help", "--version"):
            completed = subprocess.run([str(command), flag], cwd=work, env=env,
                                       check=True, text=True, capture_output=True)
            results[flag] = completed.stdout.strip()
        completed = subprocess.run([str(python), "-c", SMOKE], cwd=work, env=env,
                                   text=True, capture_output=True)
        if completed.returncode:
            raise RuntimeError("Installed widget smoke failed:\n" + completed.stderr)
        results["smoke"] = json.loads(completed.stdout.strip().splitlines()[-1])
        results["source"] = args.source
        results["fresh_venv"] = True
        results["isolated_home"] = True
        results["autostart_or_service_changes"] = False
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
