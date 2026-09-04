import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication, QLabel

from claude_widget import (
    TERMINAL_SESSION_ATTENTION_IDLE_S,
    TERMINAL_SESSION_TOOLS,
    TerminalSession,
    TerminalSessionsRow,
    TerminalSessionsSnapshot,
    TerminalTabsPanel,
    _terminal_ancestor_pid,
    focus_terminal_session,
    load_terminal_state,
    read_terminal_sessions,
    save_terminal_state,
)

CLK_TCK = 100
PTS3 = (136 << 8) | 3  # /dev/pts/3 encoded as a stat tty_nr


def make_proc(
    root: Path,
    pid: int,
    comm: str,
    *,
    ppid: int = 1,
    tty_nr: int = 0,
    cpu_ticks: int = 0,
    wchar: int = 0,
    starttime: int = 100_000,
    cwd: str = "/home/sam/claude-workspace/demo-project",
    children: tuple[int, ...] = (),
):
    proc_dir = root / str(pid)
    task_dir = proc_dir / "task" / str(pid)
    task_dir.mkdir(parents=True)
    # Fields per proc(5): pid (comm) state ppid pgrp session tty_nr tpgid
    # flags minflt cminflt majflt cmajflt utime stime cutime cstime priority
    # nice num_threads itrealvalue starttime ...
    (proc_dir / "stat").write_text(
        f"{pid} ({comm}) S {ppid} 0 0 {tty_nr} 0 0 0 0 0 0 "
        f"{cpu_ticks} 0 0 0 20 0 1 0 {starttime} 0 0"
    )
    (proc_dir / "io").write_text(f"rchar: 0\nwchar: {wchar}\n")
    (task_dir / "children").write_text(" ".join(str(c) for c in children))
    if cwd:
        os.symlink(cwd, proc_dir / "cwd")


class ReadTerminalSessionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)

    def _read(self, prev=None, parked=frozenset(), now=1_000.0):
        return read_terminal_sessions(
            prev or {}, set(parked), now=now, proc_root=self.proc, clk_tck=CLK_TCK
        )

    def test_finds_agents_on_pts_and_skips_headless_and_other_comms(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3)
        make_proc(self.proc, 200, "opencode", tty_nr=0)  # headless serve
        make_proc(self.proc, 300, "bash", tty_nr=PTS3)

        snapshot, _ = self._read()

        self.assertEqual(snapshot.error, "")
        self.assertEqual(len(snapshot.sessions), 1)
        session = snapshot.sessions[0]
        self.assertEqual(session.pid, 100)
        self.assertEqual(session.tool, "CLAUDE")
        self.assertEqual(session.tty, "pts/3")
        self.assertEqual(session.project, "demo-project")

    def test_busy_when_cpu_delta_exceeds_threshold_idle_when_below(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, cpu_ticks=1000)
        _, state = self._read(now=1_000.0)

        # 100 ticks over 10s = 10% CPU: above the 3% claude threshold.
        (self.proc / "100" / "stat").write_text(
            f"100 (claude) S 1 0 0 {PTS3} 0 0 0 0 0 0 1100 0 0 0 20 0 1 0 100000 0 0"
        )
        snapshot, state = self._read(prev=state, now=1_010.0)
        self.assertTrue(snapshot.sessions[0].busy)

        # 1 tick over the next 10s = 0.1% CPU: idle.
        (self.proc / "100" / "stat").write_text(
            f"100 (claude) S 1 0 0 {PTS3} 0 0 0 0 0 0 1101 0 0 0 20 0 1 0 100000 0 0"
        )
        snapshot, state = self._read(prev=state, now=1_020.0)
        self.assertFalse(snapshot.sessions[0].busy)

    def test_recent_tool_child_marks_busy_but_startup_children_do_not(self):
        # Child started 100s after the session: an active tool.
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, starttime=100_000,
                  children=(150,))
        make_proc(self.proc, 150, "bash", ppid=100, starttime=110_000)
        # Child started 1s after the session: a baseline MCP/shell helper.
        make_proc(self.proc, 200, "claude", tty_nr=(136 << 8) | 4,
                  starttime=100_000, children=(250,))
        make_proc(self.proc, 250, "node", ppid=200, starttime=100_100)

        _, state = self._read(now=1_000.0)
        snapshot, _ = self._read(prev=state, now=1_010.0)

        by_pid = {s.pid: s for s in snapshot.sessions}
        self.assertTrue(by_pid[100].busy)
        self.assertFalse(by_pid[200].busy)

    def test_idle_past_threshold_needs_attention_and_parked_suppresses(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3)
        _, state = self._read(now=1_000.0)

        later = 1_000.0 + TERMINAL_SESSION_ATTENTION_IDLE_S + 10
        snapshot, state = self._read(prev=state, now=later)
        session = snapshot.sessions[0]
        self.assertFalse(session.busy)
        self.assertTrue(session.needs_attention)
        self.assertGreaterEqual(session.idle_seconds,
                                TERMINAL_SESSION_ATTENTION_IDLE_S)

        snapshot, _ = self._read(prev=state, parked={session.key}, now=later + 1)
        session = snapshot.sessions[0]
        self.assertTrue(session.parked)
        self.assertFalse(session.needs_attention)

    def test_first_sight_gets_grace_even_for_old_processes(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, starttime=5)

        snapshot, _ = self._read(now=1_000_000.0)

        session = snapshot.sessions[0]
        self.assertFalse(session.needs_attention)
        self.assertEqual(session.idle_seconds, 0.0)

    def test_nested_agent_process_is_deduped_to_its_ancestor(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, children=(200,))
        make_proc(self.proc, 200, "bash", ppid=100, tty_nr=PTS3, children=(300,))
        make_proc(self.proc, 300, "claude", ppid=200, tty_nr=PTS3)

        snapshot, _ = self._read()

        self.assertEqual([s.pid for s in snapshot.sessions], [100])

    def test_comm_with_spaces_and_parens_is_parsed(self):
        make_proc(self.proc, 100, "tricky (a b)", tty_nr=PTS3)
        make_proc(self.proc, 200, "codex", tty_nr=PTS3)

        snapshot, _ = self._read()

        self.assertEqual([s.tool for s in snapshot.sessions], ["CODEX"])

    def test_rapid_rescan_carries_busy_state_forward(self):
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, cpu_ticks=1000)
        _, state = self._read(now=1_000.0)
        (self.proc / "100" / "stat").write_text(
            f"100 (claude) S 1 0 0 {PTS3} 0 0 0 0 0 0 1100 0 0 0 20 0 1 0 100000 0 0"
        )
        snapshot, state = self._read(prev=state, now=1_010.0)
        self.assertTrue(snapshot.sessions[0].busy)

        # Re-scan 0.5s later with no new CPU: too soon to judge, stay busy.
        snapshot, _ = self._read(prev=state, now=1_010.5)
        self.assertTrue(snapshot.sessions[0].busy)

    def test_missing_proc_root_reports_error(self):
        snapshot, state = read_terminal_sessions(
            {}, set(), now=1.0, proc_root=self.proc / "missing", clk_tck=CLK_TCK
        )

        self.assertNotEqual(snapshot.error, "")
        self.assertEqual(snapshot.sessions, [])
        self.assertEqual(state, {})

    def test_terminal_writes_mark_busy_even_when_cpu_is_flat(self):
        # An agent waiting on the API barely uses CPU but keeps redrawing its
        # spinner/timer, so terminal write volume is the working signal.
        make_proc(self.proc, 100, "claude", tty_nr=PTS3, wchar=1_000_000)
        _, state = self._read(now=1_000.0)

        # 50 KB over 10s = 5 KB/s of terminal output: working.
        (self.proc / "100" / "io").write_text("rchar: 0\nwchar: 1051200\n")
        snapshot, state = self._read(prev=state, now=1_010.0)
        self.assertTrue(snapshot.sessions[0].busy)

        # 100 bytes over the next 10s: an idle prompt.
        (self.proc / "100" / "io").write_text("rchar: 0\nwchar: 1051300\n")
        snapshot, _ = self._read(prev=state, now=1_020.0)
        self.assertFalse(snapshot.sessions[0].busy)

    def test_config_covers_all_three_agent_clis(self):
        comms = {comm for comm, _, _, _ in TERMINAL_SESSION_TOOLS}
        self.assertEqual(comms, {"claude", "codex", "opencode"})


class TerminalStatePersistenceTest(unittest.TestCase):
    def test_round_trip_prunes_dead_sessions_from_parked_and_notes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "terminal_sessions.json"
            save_terminal_state(
                {"1:2", "3:4"},
                {"1:2": "deploying", "3:4": "old", "5:6": "gone"},
                live_keys={"1:2"},
                path=path,
            )

            parked, notes = load_terminal_state(path)
            self.assertEqual(parked, {"1:2"})
            self.assertEqual(notes, {"1:2": "deploying"})
            # Atomic write leaves no temp file behind.
            self.assertEqual(sorted(p.name for p in Path(tmpdir).iterdir()),
                             ["terminal_sessions.json"])

    def test_load_tolerates_missing_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "terminal_sessions.json"
            self.assertEqual(load_terminal_state(path), (set(), {}))
            path.write_text("{corrupt")
            self.assertEqual(load_terminal_state(path), (set(), {}))

    def test_empty_notes_are_dropped_on_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "terminal_sessions.json"
            save_terminal_state(set(), {"1:2": "", "3:4": "  "}, path=path)
            self.assertEqual(load_terminal_state(path), (set(), {}))


def _session(key="1:1", tool="CLAUDE", project="demo", tty="pts/1", pid=None,
             busy=False, parked=False, idle_seconds=0.0, needs_attention=False,
             cwd="/home/sam/demo"):
    return TerminalSession(
        key=key, tool=tool, project=project, cwd=cwd, tty=tty,
        pid=pid if pid is not None else int(key.split(":")[0]),
        busy=busy, parked=parked, idle_seconds=idle_seconds,
        needs_attention=needs_attention,
    )


def _snapshot():
    return TerminalSessionsSnapshot(
        sessions=[
            _session(key="1:1", project="busy-proj", busy=True),
            _session(key="2:1", project="stale-proj", tty="pts/2",
                     idle_seconds=720.0, needs_attention=True),
            _session(key="3:1", project="parked-proj", tty="pts/3",
                     idle_seconds=9_000.0, parked=True),
            _session(key="4:1", project="fresh-idle", tty="pts/4",
                     idle_seconds=45.0),
        ],
        updated_at=1_000.0,
    )


class TerminalSessionsRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_placeholder_before_first_snapshot(self):
        row = TerminalSessionsRow()
        self.assertEqual(row.label_text(), "TABS")
        self.assertEqual(row.summary_text(), "—")
        self.assertEqual(row.session_lines(), [])

    def test_summary_counts_tabs_and_attention(self):
        row = TerminalSessionsRow()
        row.set_data(_snapshot())
        self.assertEqual(row.summary_text(), "4 OPEN · 1 NEED YOU")

        quiet = TerminalSessionsSnapshot(
            sessions=[_session(busy=True)], updated_at=1.0
        )
        row.set_data(quiet)
        self.assertEqual(row.summary_text(), "1 OPEN · OK")

    def test_lines_order_attention_idle_busy_then_parked(self):
        row = TerminalSessionsRow()
        row.set_data(_snapshot())

        lines = row.session_lines()
        self.assertEqual(
            [(line[1], line[3]) for line in lines],
            [
                ("stale-proj", "NEEDS YOU 12m"),
                ("fresh-idle", "WAITING 45s"),
                ("busy-proj", "WORKING"),
                ("parked-proj", "PARKED"),
            ],
        )
        self.assertEqual(lines[0][0], "CLAUDE")
        self.assertEqual(lines[0][2], "pts/2")

    def test_click_requests_panel_toggle_and_height_stays_fixed(self):
        row = TerminalSessionsRow()
        row.set_data(_snapshot())
        toggles = []
        row.panel_toggle_requested.connect(lambda: toggles.append(True))

        row.mousePressEvent(Mock())

        self.assertEqual(toggles, [True])
        self.assertEqual(row.height(), row._COLLAPSED_H)

    def test_panel_open_state_is_tracked_for_the_arrow(self):
        row = TerminalSessionsRow()
        self.assertFalse(row._panel_open)
        row.set_panel_open(True)
        self.assertTrue(row._panel_open)


class TerminalTabsPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, snapshot=None, notes=None):
        panel = TerminalTabsPanel()
        panel.set_data(snapshot or _snapshot(), notes or {})
        return panel

    def test_builds_cards_in_attention_first_order(self):
        panel = self._panel()

        cards = panel.card_summaries()
        self.assertEqual(
            [(key, project, status) for key, project, status, _ in cards],
            [
                ("2:1", "stale-proj", "NEEDS YOU 12m"),
                ("4:1", "fresh-idle", "WAITING 45s"),
                ("1:1", "busy-proj", "WORKING"),
                ("3:1", "parked-proj", "PARKED"),
            ],
        )

    def test_header_carries_the_summary(self):
        panel = self._panel()
        self.assertIn("4 OPEN · 1 NEED YOU", panel.header_text())

    def test_park_buttons_emit_the_inverted_state(self):
        panel = self._panel()
        received = []
        panel.parked_toggled.connect(lambda key, parked: received.append((key, parked)))

        park_labels = {key: label for key, _, _, label in panel.card_summaries()}
        self.assertEqual(park_labels["3:1"], "UNPARK")
        self.assertEqual(park_labels["2:1"], "PARK")

        panel.click_park("2:1")
        panel.click_park("3:1")
        self.assertEqual(received, [("2:1", True), ("3:1", False)])

    def test_note_edits_prefill_and_emit_on_finish(self):
        panel = self._panel(notes={"2:1": "waiting on CI"})
        received = []
        panel.note_changed.connect(lambda key, text: received.append((key, text)))

        self.assertEqual(panel.note_text("2:1"), "waiting on CI")

        panel.set_note_text("2:1", "rebased, rerunning")
        self.assertEqual(received, [("2:1", "rebased, rerunning")])

    def test_set_data_defers_rebuild_while_a_note_is_being_edited(self):
        panel = self._panel()
        replacement = TerminalSessionsSnapshot(
            sessions=[_session(key="9:1", project="brand-new", busy=True)],
            updated_at=2.0,
        )

        with patch.object(panel, "_editor_focused", return_value=True):
            panel.set_data(replacement, {})
            self.assertEqual(panel.card_summaries()[0][1], "stale-proj")

        panel.flush_pending()
        self.assertEqual(panel.card_summaries()[0][1], "brand-new")

    def test_group_headers_separate_working_from_waiting(self):
        panel = self._panel()
        self.assertEqual(
            panel.group_titles(),
            ["NEEDS YOU", "WAITING", "WORKING", "PARKED"],
        )

    def test_clicking_a_tab_label_requests_navigation(self):
        panel = self._panel()
        received = []
        panel.navigate_requested.connect(lambda key: received.append(key))

        panel.click_navigate("2:1")

        self.assertEqual(received, ["2:1"])

    def test_panel_and_cards_are_compact_without_a_visible_cwd_row(self):
        panel = self._panel()
        card = panel._card("2:1")

        self.assertEqual(panel.width(), 320)
        self.assertEqual(card["widget"].height(), 62)
        self.assertLess(panel.height(), 400)
        visible_labels = [
            label.text() for label in card["widget"].findChildren(QLabel)
        ]
        self.assertNotIn("/home/sam/demo", visible_labels)
        self.assertIn("/home/sam/demo", card["widget"].toolTip())
        self.assertIn("pts/2", card["widget"].accessibleDescription())
        self.assertIn("pid 2", card["widget"].accessibleDescription())

    def test_header_drag_emits_incremental_anchor_delta(self):
        panel = self._panel()
        deltas = []
        panel.drag_requested.connect(deltas.append)

        class PointerEvent:
            def __init__(self, event_type, point, *, pressed=True):
                self._type = event_type
                self._point = QPointF(point)
                self._pressed = pressed
                self.accepted = False

            def type(self):
                return self._type

            def button(self):
                return Qt.MouseButton.LeftButton

            def buttons(self):
                return (
                    Qt.MouseButton.LeftButton
                    if self._pressed
                    else Qt.MouseButton.NoButton
                )

            def globalPosition(self):
                return self._point

            def accept(self):
                self.accepted = True

        self.assertTrue(panel._header_label.property("terminalTabsDragHandle"))
        press = PointerEvent(QEvent.Type.MouseButtonPress, QPoint(100, 100))
        move = PointerEvent(QEvent.Type.MouseMove, QPoint(124, 113))
        release = PointerEvent(
            QEvent.Type.MouseButtonRelease, QPoint(124, 113), pressed=False
        )

        self.assertTrue(panel.eventFilter(panel._header_label, press))
        self.assertTrue(panel.eventFilter(panel._header_label, move))
        self.assertTrue(panel.eventFilter(panel._header_label, release))

        self.assertEqual(deltas, [QPoint(24, 13)])
        self.assertIsNone(panel._drag_global)


class _FakeXdotool:
    """Two terminal windows; window 20 cycles its tab titles as a ring."""

    def __init__(self, windows=None, titles=None, cycles=(), active_follows=True):
        self.windows = windows if windows is not None else [10, 20]
        self.titles = dict(titles or {10: "Terminal", 20: "other-proj"})
        self.ring = [self.titles.get(20, ""), *cycles]
        self.pos = 0
        self.active_follows = active_follows
        self.activated: list[int] = []
        self.next_sent = 0
        self.prev_sent = 0
        self._active: int | None = None

    def windows_for_pid(self, pid):
        return list(self.windows)

    def window_name(self, wid):
        return self.titles.get(wid, "")

    def activate(self, wid):
        self.activated.append(wid)
        if self.active_follows:
            self._active = wid
        return self.active_follows

    def active_window(self):
        return self._active

    def send_next_tab(self):
        self.next_sent += 1
        if len(self.ring) > 1:
            self.pos = (self.pos + 1) % len(self.ring)
            self.titles[20] = self.ring[self.pos]

    def send_prev_tab(self):
        self.prev_sent += 1
        if len(self.ring) > 1:
            self.pos = (self.pos - 1) % len(self.ring)
            self.titles[20] = self.ring[self.pos]


class _FakeGnomeActions:
    """GTK active-tab model with duplicate human titles in every tab."""

    def __init__(
        self,
        *,
        target=(20, 2),
        windows=None,
        original=None,
        tab_counts=None,
        marker_visible_after=2,
        action_available=True,
        unavailable_windows=(),
        no_active_tab_windows=(),
        fail_set=None,
        raise_set=None,
        active_follows=True,
        title_restore_ok=True,
        marker_sticks=False,
    ):
        self.windows = list(windows or [10, 20])
        self.target = target
        self.original = dict(original or {10: 1, 20: 0})
        self.indices = dict(self.original)
        self.tab_counts = dict(tab_counts or {10: 2, 20: 4})
        self.marker_visible_after = marker_visible_after
        self.action_available = action_available
        self.unavailable_windows = set(unavailable_windows)
        self.no_active_tab_windows = set(no_active_tab_windows)
        self.fail_set = fail_set
        self.raise_set = raise_set
        self.active_follows = active_follows
        self.title_restore_ok = title_restore_ok
        self.marker_sticks = marker_sticks
        self.marker = ""
        self.marker_refreshes = 0
        self.title_calls = []
        self.title_restored = False
        self.activated = []
        self.set_history = []
        self.next_sent = 0
        self.prev_sent = 0
        self._active = None

    def windows_for_pid(self, pid):
        return list(self.windows)

    def gtk_action_ref(self, wid):
        if not self.action_available or wid in self.unavailable_windows:
            return None
        return ":1.102", f"/org/gnome/Terminal/window/{wid}"

    @staticmethod
    def _wid(action_ref):
        return int(action_ref[1].rsplit("/", 1)[1])

    def gtk_active_tab(self, action_ref):
        wid = self._wid(action_ref)
        if wid in self.no_active_tab_windows:
            return None
        return self.indices[wid]

    def set_gtk_active_tab(self, action_ref, index):
        wid = self._wid(action_ref)
        self.set_history.append((wid, index))
        if self.raise_set == (wid, index):
            if 0 <= index < self.tab_counts[wid]:
                self.indices[wid] = index
            raise RuntimeError("simulated GTK setter failure")
        if self.fail_set == (wid, index):
            return False
        if 0 <= index < self.tab_counts[wid]:
            self.indices[wid] = index
        return True

    def set_terminal_title(self, tty, marker, *, save):
        self.title_calls.append((tty, marker, save))
        self.marker = marker
        if not save and self.target is not None:
            wid, index = self.target
            if self.indices.get(wid) == index:
                self.marker_refreshes += 1
        return True

    def restore_terminal_title(self, tty):
        self.title_restored = True
        if self.title_restore_ok and not self.marker_sticks:
            self.marker = ""
        return self.title_restore_ok

    def window_name(self, wid):
        if (
            self.target is not None
            and (wid, self.indices[wid]) == self.target
            and self.marker_refreshes >= self.marker_visible_after
        ):
            return self.marker
        return "coffee-explorer"

    def activate(self, wid):
        self.activated.append(wid)
        if self.active_follows:
            self._active = wid
        return self.active_follows

    def active_window(self):
        return self._active

    def send_next_tab(self):
        self.next_sent += 1

    def send_prev_tab(self):
        self.prev_sent += 1


class FocusTerminalSessionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)
        # claude(100) -> bash(50) -> xterm(40). Tests that exercise GNOME's
        # exact path replace the emulator comm explicitly.
        make_proc(self.proc, 100, "claude", ppid=50, tty_nr=PTS3)
        make_proc(self.proc, 50, "bash", ppid=40)
        make_proc(self.proc, 40, "xterm", ppid=1)

    def _use_gnome_terminal(self):
        stat_path = self.proc / "40" / "stat"
        stat_path.write_text(stat_path.read_text().replace("(xterm)", "(gnome-terminal-)"))

    def _session_(self, project="coffee-explorer"):
        return _session(
            key="100:100000", pid=100, project=project, tty="pts/3"
        )

    def test_ancestor_walk_finds_the_terminal_emulator(self):
        self.assertEqual(_terminal_ancestor_pid(100, self.proc), 40)
        make_proc(self.proc, 999, "claude", ppid=1, tty_nr=PTS3)
        self.assertIsNone(_terminal_ancestor_pid(999, self.proc))

    def test_direct_title_match_activates_without_cycling(self):
        runner = _FakeXdotool(titles={10: "Terminal", 20: "coffee-explorer"})

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertTrue(ok, detail)
        self.assertEqual(runner.activated, [20])
        self.assertEqual(runner.next_sent, 0)

    def test_cycles_tabs_until_the_title_matches(self):
        runner = _FakeXdotool(
            titles={10: "zzz", 20: "other-proj"},
            cycles=["second-proj", "coffee-explorer"],
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertTrue(ok, detail)
        # Window 10 gets one probe key (no title change, so it is restored
        # with one ctrl+Prior); window 20 matches after two cycles.
        self.assertEqual(runner.next_sent, 3)
        self.assertEqual(runner.prev_sent, 1)
        self.assertEqual(runner.titles[20], "coffee-explorer")

    def test_never_sends_keys_when_activation_does_not_take(self):
        runner = _FakeXdotool(active_follows=False)

        ok, _ = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertEqual(runner.next_sent, 0)

    def test_title_match_does_not_succeed_when_activation_fails(self):
        runner = _FakeXdotool(
            titles={10: "Terminal", 20: "coffee-explorer"},
            active_follows=False,
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("best-effort", detail)
        self.assertEqual(runner.next_sent, 0)

    def test_failed_cycling_restores_the_original_tab(self):
        runner = _FakeXdotool(
            titles={10: "zzz", 20: "aaa"},
            cycles=["bbb", "ccc"],
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc,
            settle=0, max_tabs=4,
        )

        self.assertFalse(ok)
        self.assertIn("never matched", detail)
        # Every cycling key was undone: both windows show their original tab.
        self.assertEqual(runner.prev_sent, runner.next_sent)
        self.assertEqual(runner.titles[20], "aaa")

    def test_gnome_selects_exact_tty_despite_duplicate_project_titles(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(target=(20, 2), marker_visible_after=2)

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertTrue(ok, detail)
        self.assertIn("exact pts/3 tab 2", detail)
        self.assertEqual(runner.activated, [20])
        self.assertEqual(runner.indices[10], 1)  # nonmatching window restored
        self.assertEqual(runner.indices[20], 2)  # exact target remains selected
        self.assertGreaterEqual(runner.marker_refreshes, 2)
        self.assertTrue(runner.title_restored)
        self.assertEqual(runner.next_sent, 0)
        self.assertEqual(runner.prev_sent, 0)

    def test_gnome_failure_restores_every_index_and_title_without_keys(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(target=None)

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc,
            settle=0, max_tabs=8,
        )

        self.assertFalse(ok)
        self.assertIn("no GNOME Terminal tab owns pts/3", detail)
        self.assertEqual(runner.indices, runner.original)
        self.assertEqual(runner.activated, [])
        self.assertTrue(runner.title_restored)
        self.assertEqual((runner.next_sent, runner.prev_sent), (0, 0))

    def test_gnome_action_failure_is_fail_closed_and_restores_index(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(target=None, fail_set=(20, 1))

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("selection failed", detail)
        self.assertEqual(runner.indices, runner.original)
        self.assertEqual(runner.activated, [])
        self.assertTrue(runner.title_restored)
        self.assertEqual((runner.next_sent, runner.prev_sent), (0, 0))

    def test_gnome_exception_after_mutation_rolls_back_original_index(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(
            target=None,
            original={10: 1, 20: 2},
            raise_set=(20, 1),
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("exact-tab selection failed", detail)
        self.assertEqual(runner.indices, runner.original)
        self.assertTrue(runner.title_restored)

    def test_gnome_title_restore_failure_rolls_back_matched_target(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(
            target=(20, 2), title_restore_ok=False
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("title", detail)
        self.assertIn("did not restore", detail)
        self.assertEqual(runner.indices, runner.original)

    def test_gnome_visible_marker_after_restore_rolls_back_matched_target(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(target=(20, 2), marker_sticks=True)

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("remained visible", detail)
        self.assertEqual(runner.indices, runner.original)

    def test_gnome_activation_failure_restores_the_previously_active_tab(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(target=(20, 2), active_follows=False)

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("would not activate", detail)
        self.assertEqual(runner.indices, runner.original)
        self.assertTrue(runner.title_restored)

    def test_gnome_without_gtk_action_does_not_use_ambiguous_title_fallback(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(action_available=False)

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("no GNOME Terminal window", detail)
        self.assertEqual(runner.activated, [])
        self.assertEqual(runner.title_calls, [])
        self.assertEqual((runner.next_sent, runner.prev_sent), (0, 0))

    def test_gnome_skips_auxiliary_window_without_active_tab_action(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(
            target=(20, 2), no_active_tab_windows={10}
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertTrue(ok, detail)
        self.assertEqual(runner.activated, [20])
        self.assertFalse(any(wid == 10 for wid, _ in runner.set_history))

    def test_gnome_selects_target_in_a_single_tab_window(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions(
            windows=[20],
            target=(20, 0),
            original={20: 0},
            tab_counts={20: 1},
            marker_visible_after=1,
        )

        ok, detail = focus_terminal_session(
            self._session_(), runner=runner, proc_root=self.proc, settle=0
        )

        self.assertTrue(ok, detail)
        self.assertIn("tab 0", detail)

    def test_gnome_rejects_non_numeric_session_identity_before_tty_write(self):
        self._use_gnome_terminal()
        runner = _FakeGnomeActions()
        session = self._session_()
        session.key = "100:not-numeric"

        ok, detail = focus_terminal_session(
            session, runner=runner, proc_root=self.proc, settle=0
        )

        self.assertFalse(ok)
        self.assertIn("invalid numeric session", detail)
        self.assertEqual(runner.title_calls, [])

    def test_gnome_revalidates_start_time_and_tty_before_title_write(self):
        self._use_gnome_terminal()
        cases = (
            ("100:99999", "pts/3", "start time changed"),
            ("100:100000", "pts/4", "pts changed"),
        )
        for key, tty, expected in cases:
            with self.subTest(key=key, tty=tty):
                runner = _FakeGnomeActions()
                session = self._session_()
                session.key = key
                session.tty = tty

                ok, detail = focus_terminal_session(
                    session, runner=runner, proc_root=self.proc, settle=0
                )

                self.assertFalse(ok)
                self.assertIn(expected, detail)
                self.assertEqual(runner.title_calls, [])
                self.assertEqual(runner.set_history, [])


if __name__ == "__main__":
    unittest.main()
