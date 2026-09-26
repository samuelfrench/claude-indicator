"""Small Linux process guard and systemd integration for the desktop widget."""

import faulthandler
import fcntl
import os
from pathlib import Path
import signal
import socket
import stat
import time


class InstanceLock:
    """Hold the lock until process exit; never unlink a possibly locked inode."""

    def __init__(self, path=None):
        if path is None:
            # A shared path for both direct and service launches, even when their
            # XDG_RUNTIME_DIR environments differ.
            path = Path.home() / ".local/state/claude-indicator/widget.lock"
        self.path = Path(path)
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise OSError("Widget lock must be an owned regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
            os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return True

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def notify(message, environ=None):
    """Send sd_notify without a systemd/Python dependency or blocking the UI."""
    env = os.environ if environ is None else environ
    address = env.get("NOTIFY_SOCKET", "")
    if not address or address[0] not in ("/", "@"):
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(message.encode("utf-8"), address)
        return True
    except OSError:
        return False


def watchdog_interval(environ=None):
    env = os.environ if environ is None else environ
    try:
        if int(env.get("WATCHDOG_PID", str(os.getpid()))) != os.getpid():
            return None
        usec = int(env.get("WATCHDOG_USEC", "0"))
    except ValueError:
        return None
    return usec / 3_000_000 if usec > 0 else None


class QtServiceRuntime:
    """Only the Qt event loop can report readiness and continued health."""

    def __init__(self, app):
        from PySide6.QtCore import QTimer

        self.app = app
        self.interval = watchdog_interval()
        self.last_heartbeat = 0.0
        self.ready_sent = False
        self.stop_requested = False
        self.previous_handlers = {}
        self.timer = QTimer(app)
        # Also lets Python dispatch SIGTERM while Qt is otherwise idle.
        self.timer.setInterval(max(1, min(1000, int((self.interval or 1) * 1000))))
        self.timer.timeout.connect(self.tick)
        app.aboutToQuit.connect(self.stopping)

    def start(self):
        faulthandler.enable(all_threads=True)
        for signum in (signal.SIGTERM, signal.SIGINT):
            self.previous_handlers[signum] = signal.signal(signum, self.request_stop)
        self.timer.start()

    def request_stop(self, _signum, _frame):
        self.stop_requested = True

    def tick(self):
        if self.stop_requested:
            self.app.quit()
            return
        if not self.ready_sent:
            notify("READY=1\nSTATUS=Widget event loop running")
            self.ready_sent = True
        now = time.monotonic()
        if self.interval is not None and now - self.last_heartbeat >= self.interval:
            notify("WATCHDOG=1")
            self.last_heartbeat = now

    def stopping(self):
        self.timer.stop()
        notify("STOPPING=1\nSTATUS=Widget shutting down")
        for signum, handler in self.previous_handlers.items():
            signal.signal(signum, handler)
        self.previous_handlers.clear()
