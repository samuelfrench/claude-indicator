"""Tests must never make provider requests; responses are explicitly mocked."""

import subprocess
import shlex
import urllib.request
from pathlib import Path

import pytest
import requests


@pytest.fixture(autouse=True)
def forbid_network_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unmocked network request blocked by the test suite")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


@pytest.fixture(autouse=True)
def forbid_provider_cli_processes(monkeypatch):
    real_popen = subprocess.Popen

    def guarded(command, *args, **kwargs):
        parts = shlex.split(command) if isinstance(command, str) else command
        if parts and Path(str(parts[0])).name in {"gh", "codex", "claude", "grok", "opencode", "cursor", "cursor-agent", "agent"}:
            raise AssertionError("Unmocked provider CLI blocked by the test suite")
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded)


@pytest.fixture(autouse=True)
def isolate_claude_statusline_settings(monkeypatch, tmp_path):
    """Keep the owner's ~/.claude/settings.json statusLine from feeding fetch().

    ``read_claude_statusline_usage`` reads ``Path.home()`` at call time; on a
    host with the status-line feed configured, every ``ClaudeUsageClient.fetch``
    test would otherwise return live local quota data instead of exercising
    the mocked API path.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
