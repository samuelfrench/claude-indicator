import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from scripts import indicator_service
from widget_runtime import InstanceLock, notify, watchdog_interval


def test_instance_lock_released_on_process_death(tmp_path):
    path = tmp_path / "widget.lock"
    code = """
import sys, time
from widget_runtime import InstanceLock
lock = InstanceLock(sys.argv[1])
assert lock.acquire()
print('locked', flush=True)
time.sleep(60)
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        contender = InstanceLock(path)
        assert not contender.acquire()
        child.kill()
        child.wait(timeout=5)
        assert contender.acquire()
        assert path.stat().st_mode & 0o777 == 0o600
        contender.close()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_lock_rejects_symlinks(tmp_path):
    target = tmp_path / "target"
    target.write_text("unchanged")
    path = tmp_path / "lock"
    path.symlink_to(target)
    with pytest.raises(OSError):
        InstanceLock(path).acquire()
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("abstract", [False, True])
def test_notify_real_unix_socket(tmp_path, abstract):
    address = f"@indicator-test-{os.getpid()}" if abstract else str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("\0" + address[1:] if abstract else address)
        server.settimeout(1)
        assert notify("READY=1\nWATCHDOG=1", {"NOTIFY_SOCKET": address})
        assert server.recv(1024) == b"READY=1\nWATCHDOG=1"
    assert not notify("READY=1", {"NOTIFY_SOCKET": str(tmp_path / "missing")})
    assert not notify("READY=1", {})


def test_watchdog_is_only_for_this_process():
    assert watchdog_interval({"WATCHDOG_USEC": "90000000"}) == 30
    assert watchdog_interval({"WATCHDOG_USEC": "90000000", "WATCHDOG_PID": str(os.getpid() + 1)}) is None
    for invalid in ("", "bad", "0", "-1"):
        assert watchdog_interval({"WATCHDOG_USEC": invalid}) is None


def test_intentional_quit_with_pending_qthread_exits_cleanly(tmp_path):
    code = """
import time
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QWidget
import claude_widget
class BusyWorker(QThread):
    def run(self):
        time.sleep(30)
class TestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = BusyWorker(self)
        self.worker.start()
        QTimer.singleShot(50, QApplication.quit)
    def shutdown(self):
        self._shutdown_workers_pending = self.worker.isRunning()
    def clamp_to_available_screen(self):
        pass
claude_widget.ClaudeWidget = TestWidget
claude_widget.main()
"""
    env = dict(os.environ, HOME=str(tmp_path), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert "Destroyed while" not in result.stderr


def test_qt_event_loop_readiness_heartbeat_and_clean_sigterm(tmp_path):
    address = str(tmp_path / "notify")
    code = """
import signal, time
from PySide6.QtCore import QCoreApplication, QTimer
from widget_runtime import QtServiceRuntime
app = QCoreApplication([])
runtime = QtServiceRuntime(app)
runtime.start()
# No event processing: neither readiness nor a watchdog heartbeat may be sent.
print('constructed', flush=True)
time.sleep(.2)
def freeze():
    print('frozen', flush=True)
    time.sleep(.3)
QTimer.singleShot(100, freeze)
raise SystemExit(app.exec())
"""
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(address)
        server.settimeout(3)
        env = dict(os.environ, NOTIFY_SOCKET=address, WATCHDOG_USEC="90000")
        env.pop("WATCHDOG_PID", None)
        child = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "constructed"
            assert not select.select([server], [], [], .1)[0]
            assert server.recv(1024).startswith(b"READY=1")
            assert server.recv(1024) == b"WATCHDOG=1"
            assert child.stdout.readline().strip() == "frozen"
            # Drain messages sent before entering the blocking callback.
            while select.select([server], [], [], 0)[0]:
                server.recv(1024)
            assert not select.select([server], [], [], .15)[0]
            assert server.recv(1024) == b"WATCHDOG=1"
            child.terminate()
            assert child.wait(timeout=3) == 0
            messages = []
            while select.select([server], [], [], 0)[0]:
                messages.append(server.recv(1024))
            assert any(message.startswith(b"STOPPING=1") for message in messages)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_install_uses_explicit_interpreter_and_checkout(tmp_path):
    checkout = tmp_path / "checkout with spaces"
    checkout.mkdir()
    (checkout / "claude_widget.py").touch()
    config = tmp_path / "config"
    with patch.object(indicator_service.subprocess, "run") as run:
        unit, desktop = indicator_service.install(Path(sys.executable), checkout, config, "/opt/qt/lib")
    run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)
    assert f'ExecStart="{sys.executable}" "{checkout}/claude_widget.py"' in unit.read_text()
    assert 'Environment="LD_LIBRARY_PATH=/opt/qt/lib"' in unit.read_text()
    assert "Restart=on-failure" in unit.read_text()
    assert "WatchdogSec=90" in unit.read_text()
    assert "LimitCORE=0" in unit.read_text()
    assert "PartOf=graphical-session.target" in unit.read_text()
    assert f'"{checkout}/scripts/indicator_service.py" launch' in desktop.read_text()
    verified = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True)
    assert verified.returncode == 0, verified.stderr


def test_launch_imports_only_display_environment_and_unsets_stale():
    with patch.dict(os.environ, {"DISPLAY": ":1", "PRIVATE_TOKEN": "never-import"}, clear=True), patch.object(indicator_service.subprocess, "run") as run:
        indicator_service.launch()
    calls = [call.args[0] for call in run.call_args_list]
    assert calls == [
        ["systemctl", "--user", "unset-environment", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP"],
        ["systemctl", "--user", "import-environment", "DISPLAY"],
        ["systemctl", "--user", "start", "claude-indicator.service"],
    ]


def test_launch_without_display_does_not_mutate_manager():
    with patch.dict(os.environ, {}, clear=True), patch.object(indicator_service.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="graphical session"):
            indicator_service.launch()
    run.assert_not_called()
