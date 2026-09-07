"""Read-only Linux terminal inventory and durable, boot-scoped recovery history.

Only process names, working directories and terminal metadata are collected.
Arguments, environment, shell history and terminal contents are never read.
"""

import json
import os
from pathlib import Path
import sqlite3
import time


DEFAULT_PATH = Path.home() / ".local/state/claude-indicator/terminals.sqlite3"
_EMULATORS = {
    "gnome-terminal-server", "gnome-terminal-", "konsole", "xterm", "uxterm",
    "alacritty", "kitty", "wezterm-gui", "foot", "xfce4-terminal", "tilix",
    "mate-terminal", "lxterminal", "terminator", "urxvt", "st", "ghostty",
    "sshd", "tmux", "tmux: server", "screen",
}


def read_boot_id(proc_root=Path("/proc")):
    value = (Path(proc_root) / "sys/kernel/random/boot_id").read_text().strip()
    if not value:
        raise OSError("The kernel boot identity is unavailable")
    return value


def _stat(path):
    raw = path.read_text()
    left, right = raw.index("("), raw.rindex(")")
    fields = raw[right + 2:].split()
    return {
        "pid": int(raw[:left].strip()), "comm": raw[left + 1:right],
        "ppid": int(fields[1]), "pgrp": int(fields[2]),
        "session": int(fields[3]), "tty_nr": int(fields[4]),
        "foreground": int(fields[5]), "starttime": int(fields[19]),
    }


def _tty_name(number):
    device = number & 0xffffffff
    major, minor = os.major(device), os.minor(device)
    if 136 <= major <= 143:
        return f"pts/{(major - 136) * 256 + minor}"
    if major == 4 and minor < 64:
        return f"tty{minor}"
    return f"tty:{major}:{minor}"


def scan_terminals(proc_root=Path("/proc"), now=None):
    """Return one record per owned controlling terminal, including plain shells.

    Root/boot identity read failures propagate; races involving individual exited
    processes are skipped. A failed scan must not be saved as an empty snapshot.
    """
    proc_root = Path(proc_root)
    boot_id = read_boot_id(proc_root)
    stamp = time.time() if now is None else now
    processes = {}
    # Materialize the directory before collection so root enumeration errors fail.
    for directory in list(proc_root.iterdir()):
        if not directory.name.isdecimal():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            process = _stat(directory / "stat")
            try:
                process["program"] = Path(os.readlink(directory / "exe")).name
            except OSError:
                process["program"] = process["comm"]
            try:
                process["cwd"] = os.readlink(directory / "cwd")
            except OSError:
                process["cwd"] = ""
            # Do not combine metadata from a reused PID with its old identity.
            check = _stat(directory / "stat")
            if (check["starttime"], check["tty_nr"]) != (
                process["starttime"], process["tty_nr"]
            ):
                continue
            processes[process["pid"]] = process
        except (OSError, ValueError, IndexError):
            continue

    groups = {}
    for process in processes.values():
        if process["tty_nr"]:
            groups.setdefault(process["tty_nr"], []).append(process)
    result = []
    for tty_nr, members in groups.items():
        root = min(members, key=lambda p: (
            p["pid"] != p["session"], p["starttime"], p["pid"]
        ))
        ordered = sorted(members, key=lambda p: (
            not (p["pgrp"] > 0 and p["pgrp"] == p["foreground"]),
            p["pid"] != p["pgrp"], p["starttime"], p["pid"],
        ))
        terminal, window = "PTY", None
        ancestor, seen = root, set()
        while ancestor and ancestor["pid"] not in seen:
            seen.add(ancestor["pid"])
            if ancestor["program"] in _EMULATORS or ancestor["comm"] in _EMULATORS:
                terminal, window = ancestor["program"], ancestor["pid"]
                break
            ancestor = processes.get(ancestor["ppid"])
        programs = list(dict.fromkeys(p["program"] for p in ordered))
        result.append({
            "key": f"{boot_id}:{root['pid']}:{root['starttime']}",
            "boot_id": boot_id, "tty": _tty_name(tty_nr),
            "pid": root["pid"], "starttime": root["starttime"],
            "cwd": next((p["cwd"] for p in ordered if p["cwd"] and
                         p["pgrp"] > 0 and p["pgrp"] == p["foreground"]),
                        root["cwd"]),
            "programs": programs, "terminal": terminal, "window": window,
            "last_seen": stamp,
        })
    return sorted(result, key=lambda row: (row["tty"], row["pid"]))


class TerminalRecoveryStore:
    """Committed captures survive restart; old boots and exited terminals remain.

    Each operation uses its own connection, permitting worker-thread use without
    sharing SQLite connection state. SQLite's full synchronous rollback journal
    makes a capture all-or-nothing, including the boot's final snapshot membership.
    """

    def __init__(self, path=None, *, boot_id=None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.boot_id = read_boot_id() if boot_id is None else boot_id
        self._captured = False
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        # Create privately before SQLite opens it (rather than chmod after write).
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        db = self._connect()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS boots (
                    boot_id TEXT PRIMARY KEY,
                    captured REAL NOT NULL,
                    capture_id INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS terminals (
                    key TEXT PRIMARY KEY,
                    boot_id TEXT NOT NULL,
                    record TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    capture_id INTEGER NOT NULL,
                    closed_at REAL
                );
            """)
        finally:
            db.close()
        # Persist initial file creation in addition to SQLite's content commits.
        directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    def capture(self, records, now=None):
        stamp = time.time() if now is None else now
        records = list(records)
        keys = set()
        serialized = []
        for record in records:
            if record["boot_id"] != self.boot_id:
                raise ValueError("Terminal snapshot belongs to a different boot")
            if record["key"] in keys:
                raise ValueError("Duplicate terminal identity in snapshot")
            keys.add(record["key"])
            serialized.append((record["key"], json.dumps(record, allow_nan=False)))
        db = self._connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute("SELECT capture_id FROM boots WHERE boot_id=?",
                                   (self.boot_id,)).fetchone()
                capture_id = prior[0] + 1 if prior else 1
                db.execute("""INSERT INTO boots VALUES (?, ?, ?)
                    ON CONFLICT(boot_id) DO UPDATE SET
                    captured=excluded.captured, capture_id=excluded.capture_id""",
                           (self.boot_id, stamp, capture_id))
                for key, value in serialized:
                    db.execute("""INSERT INTO terminals VALUES (?, ?, ?, ?, ?, ?, NULL)
                        ON CONFLICT(key) DO UPDATE SET record=excluded.record,
                        last_seen=excluded.last_seen, capture_id=excluded.capture_id,
                        closed_at=NULL""",
                               (key, self.boot_id, value, stamp, stamp, capture_id))
                db.execute("""UPDATE terminals SET closed_at=?
                    WHERE boot_id=? AND capture_id!=? AND closed_at IS NULL""",
                           (stamp, self.boot_id, capture_id))
            self._captured = True
        finally:
            db.close()

    def entries(self):
        db = self._connect()
        try:
            rows = db.execute("""SELECT t.*, b.captured AS boot_captured,
                b.capture_id AS latest_capture FROM terminals t
                JOIN boots b ON b.boot_id=t.boot_id
                ORDER BY b.captured DESC, t.last_seen DESC, t.key""").fetchall()
        finally:
            db.close()
        result = []
        for row in rows:
            entry = json.loads(row["record"])
            present = row["capture_id"] == row["latest_capture"]
            entry.update(
                first_seen=row["first_seen"], last_seen=row["last_seen"],
                captured=row["last_seen"], boot_captured=row["boot_captured"],
                closed_at=row["closed_at"], at_boot_end=present,
                live=self._captured and present and row["boot_id"] == self.boot_id,
            )
            result.append(entry)
        return result

    def boot_snapshots(self):
        """Include empty captures so the last boot is never silently skipped."""
        db = self._connect()
        try:
            return [dict(row) for row in db.execute(
                "SELECT boot_id, captured, capture_id FROM boots ORDER BY captured DESC"
            ).fetchall()]
        finally:
            db.close()
