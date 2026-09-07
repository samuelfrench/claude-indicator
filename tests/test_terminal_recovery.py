import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from terminal_recovery import TerminalRecoveryStore, scan_terminals


def proc(root, pid, comm, *, parent=1, tty=0, session=None, group=None,
         foreground=None, start=100, cwd="/work"):
    directory = root / str(pid)
    directory.mkdir(parents=True)
    session = pid if session is None else session
    group = pid if group is None else group
    foreground = group if foreground is None else foreground
    fields = ["S", str(parent), str(group), str(session), str(tty), str(foreground)]
    fields += ["0"] * 13 + [str(start)]
    (directory / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields))
    (directory / "cwd").symlink_to(cwd)
    return directory


@pytest.fixture
def proc_root(tmp_path):
    root = tmp_path / "proc"
    boot = root / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("boot-A\n")
    return root


def record(key="one", boot="boot-A", **changes):
    value = dict(key=f"{boot}:{key}", boot_id=boot, tty="pts/1", pid=100,
                 starttime=10, cwd="/work", programs=["bash"], terminal="PTY",
                 window=None)
    value.update(changes)
    return value


def test_plain_shells_commands_and_tmux_are_grouped_by_terminal(proc_root):
    proc(proc_root, 10, "gnome-terminal-", cwd="/")
    proc(proc_root, 100, "bash", parent=10, tty=os.makedev(136, 2), foreground=101)
    proc(proc_root, 101, "python", parent=100, tty=os.makedev(136, 2),
         session=100, foreground=101, start=110, cwd="/work/build")
    proc(proc_root, 102, "worker", parent=101, tty=os.makedev(136, 2),
         session=100, group=101, foreground=101, start=111, cwd="/work/build")
    proc(proc_root, 200, "zsh", parent=10, tty=os.makedev(136, 3))
    proc(proc_root, 250, "tmux: server")
    proc(proc_root, 300, "fish", parent=250, tty=os.makedev(136, 4))
    proc(proc_root, 400, "headless-service", tty=0)
    rows = scan_terminals(proc_root, now=500)
    assert len(rows) == 3
    assert rows[0]["key"] == "boot-A:100:100"
    assert rows[0]["programs"] == ["python", "worker", "bash"]
    assert rows[0]["cwd"] == "/work/build"
    assert rows[0]["terminal"] == "gnome-terminal-"
    assert rows[0]["window"] == 10
    assert rows[1]["programs"] == ["zsh"]
    assert rows[2]["terminal"] == "tmux: server"
    assert all(row["last_seen"] == 500 for row in rows)


def test_scan_survives_exits_and_does_not_read_arguments_or_environment(proc_root):
    process = proc(proc_root, 1, "name with ) parens", tty=os.makedev(136, 9))
    (process / "cmdline").write_text("do-not-collect-private-arguments")
    (process / "environ").write_text("do-not-collect-private-environment")
    proc(proc_root, 2, "exited", tty=os.makedev(136, 8))
    (proc_root / "2/stat").unlink()
    rows = scan_terminals(proc_root)
    assert len(rows) == 1
    assert rows[0]["programs"] == ["name with ) parens"]
    assert "do-not-collect" not in str(rows)


def test_scan_excludes_other_users(proc_root, monkeypatch):
    proc(proc_root, 100, "bash", tty=os.makedev(136, 2))
    monkeypatch.setattr(os, "getuid", lambda: -1)
    assert scan_terminals(proc_root) == []


def test_versioned_executable_keeps_recognizable_program_name(proc_root):
    process = proc(proc_root, 100, "claude", tty=os.makedev(136, 2))
    (process / "exe").symlink_to("/home/user/.local/share/claude/versions/2.1.263")
    assert scan_terminals(proc_root)[0]["programs"] == ["claude"]


def test_unreadable_proc_or_boot_is_an_error(tmp_path, proc_root):
    with pytest.raises(OSError):
        scan_terminals(tmp_path / "missing")
    (proc_root / "sys/kernel/random/boot_id").write_text("")
    with pytest.raises(OSError, match="boot identity"):
        scan_terminals(proc_root)


def test_required_metadata_permission_error_is_not_an_empty_scan(proc_root, monkeypatch):
    proc(proc_root, 100, "bash", tty=os.makedev(136, 2))
    read_text = Path.read_text
    def denied(path, *args, **kwargs):
        if path == proc_root / "100/stat":
            raise PermissionError("cannot read stat")
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(OSError, match="PID 100"):
        scan_terminals(proc_root)


def test_reopen_changes_and_closed_history(tmp_path):
    path = tmp_path / "state/terminals.sqlite3"
    store = TerminalRecoveryStore(path, boot_id="boot-A")
    store.capture([record()], now=10)
    assert store.entries()[0]["live"]
    store = TerminalRecoveryStore(path, boot_id="boot-A")
    assert not store.entries()[0]["live"]  # no fresh scan since this restart
    store.capture([record(cwd="/new", programs=["make", "bash"])], now=20)
    row = store.entries()[0]
    assert (row["first_seen"], row["last_seen"], row["cwd"]) == (10, 20, "/new")
    assert row["programs"] == ["make", "bash"]
    store.capture([], now=30)
    row = store.entries()[0]
    assert row["closed_at"] == 30
    assert row["last_seen"] == 20
    assert not row["live"]
    assert not row["at_boot_end"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_new_empty_boot_preserves_exact_last_boot_snapshot(tmp_path):
    path = tmp_path / "state/terminals.sqlite3"
    previous = TerminalRecoveryStore(path, boot_id="boot-A")
    previous.capture([record("closed"), record("running")], now=10)
    previous.capture([record("running")], now=20)
    new_boot = TerminalRecoveryStore(path, boot_id="boot-B")
    new_boot.capture([], now=30)
    rows = {row["key"]: row for row in new_boot.entries()}
    assert len(rows) == 2
    assert rows["boot-A:running"]["at_boot_end"]
    assert rows["boot-A:running"]["boot_captured"] == 20
    assert rows["boot-A:running"]["closed_at"] is None
    assert not rows["boot-A:closed"]["at_boot_end"]
    assert not any(row["live"] for row in rows.values())
    assert new_boot.boot_snapshots() == [
        {"boot_id": "boot-B", "captured": 30, "capture_id": 1},
        {"boot_id": "boot-A", "captured": 20, "capture_id": 2},
    ]
    new_boot.capture([record(boot="boot-B")], now=40)
    assert len(new_boot.entries()) == 3
    assert sum(row["live"] for row in new_boot.entries()) == 1


def test_failed_transaction_preserves_complete_previous_snapshot(tmp_path):
    path = tmp_path / "state/terminals.sqlite3"
    store = TerminalRecoveryStore(path, boot_id="boot-A")
    store.capture([record()], now=10)
    # Fail after the boot capture marker and first terminal have been updated.
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_write BEFORE INSERT ON terminals
            WHEN NEW.key = 'boot-A:bad' BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="disk failure"):
        store.capture([record(cwd="/uncommitted"), record("bad")], now=20)
    rows = store.entries()
    assert len(rows) == 1
    assert rows[0]["cwd"] == "/work"
    assert rows[0]["last_seen"] == rows[0]["boot_captured"] == 10
    assert rows[0]["at_boot_end"]


def test_wrong_boot_and_duplicate_capture_rejected_without_change(tmp_path):
    store = TerminalRecoveryStore(tmp_path / "state/terminals.sqlite3", boot_id="boot-A")
    store.capture([record()], now=10)
    with pytest.raises(ValueError, match="different boot"):
        store.capture([record(boot="boot-B")], now=20)
    with pytest.raises(ValueError, match="Duplicate"):
        store.capture([record(), record()], now=20)
    assert store.entries()[0]["last_seen"] == 10


def test_sigkill_during_next_write_retains_committed_inventory(tmp_path):
    path = tmp_path / "state/terminals.sqlite3"
    code = """
import os, signal, sys
from terminal_recovery import TerminalRecoveryStore
store = TerminalRecoveryStore(sys.argv[1], boot_id='A')
store.capture([dict(key='A:1', boot_id='A', tty='pts/1', pid=1,
    starttime=10, cwd='/work/before-power-loss', programs=['make', 'bash'],
    terminal='PTY', window=None)], now=10)
db = store._connect()
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE terminals SET record='incomplete'")
db.execute('UPDATE boots SET captured=20, capture_id=2')
os.kill(os.getpid(), signal.SIGKILL)
"""
    child = subprocess.run([sys.executable, "-c", code, str(path)], timeout=15)
    assert child.returncode == -9
    reboot = TerminalRecoveryStore(path, boot_id="B")
    reboot.capture([], now=30)
    rows = reboot.entries()
    assert len(rows) == 1
    assert rows[0]["cwd"] == "/work/before-power-loss"
    assert rows[0]["programs"] == ["make", "bash"]
    assert rows[0]["boot_captured"] == 10
    assert rows[0]["at_boot_end"] and not rows[0]["live"]
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
