import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from claude_widget import ClaudeWidget
from terminal_recovery import TerminalRecoveryStore
from terminal_recovery_ui import TerminalRecoveryDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def record(boot="A", key="1", cwd="/work/coffee", programs=None):
    return dict(key=f"{boot}:{key}", boot_id=boot, tty="pts/1", pid=100,
                starttime=10, cwd=cwd, programs=programs or ["make", "bash"],
                terminal="gnome-terminal-server", window=50)


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "state/terminals.sqlite3"
    old = TerminalRecoveryStore(path, boot_id="A")
    old.capture([record(), record(key="2", cwd="/work/closed")], now=100)
    old.capture([record()], now=110)
    new = TerminalRecoveryStore(path, boot_id="B")
    new.capture([record(boot="B", cwd="/work/honey", programs=["zsh"])], now=200)
    return new


def test_previous_boot_default_search_copy_and_live_view(app, saved):
    dialog = TerminalRecoveryDialog()
    dialog.set_data(saved.entries(), saved.boot_snapshots(), saved.boot_id)
    assert dialog._view.currentText() == "Last boot snapshot"
    assert dialog._table.topLevelItemCount() == 1
    assert "/work/coffee" in dialog._details.toPlainText()
    assert "/work/closed" not in dialog._details.toPlainText()
    dialog._copy.click()
    assert "Programs: make, bash" in app.clipboard().text()
    dialog._view.setCurrentIndex(0)
    assert dialog._table.topLevelItemCount() == 1
    assert "zsh" in dialog._details.toPlainText()
    dialog._view.setCurrentIndex(2)
    assert dialog._table.topLevelItemCount() == 3
    dialog._search.setText("closed")
    assert dialog._table.topLevelItemCount() == 1
    assert "/work/closed" in dialog._details.toPlainText()
    dialog._search.setText("no such program")
    assert dialog._table.topLevelItemCount() == 0
    assert not dialog._copy.isEnabled()
    dialog.close()


def test_empty_previous_boot_does_not_fall_back_to_older_sessions(app, saved):
    saved.capture([], now=210)
    newest = TerminalRecoveryStore(saved.path, boot_id="C")
    newest.capture([], now=300)
    dialog = TerminalRecoveryDialog()
    dialog.set_data(newest.entries(), newest.boot_snapshots(), "C")
    assert dialog._view.currentText() == "Last boot snapshot"
    assert dialog._table.topLevelItemCount() == 0
    assert "previous recorded boot" in dialog._context.text()
    dialog._view.setCurrentIndex(2)
    assert dialog._table.topLevelItemCount() == 3
    dialog.close()


def test_refresh_keeps_view_query_selection_and_marks_stale_data(app, saved):
    dialog = TerminalRecoveryDialog()
    dialog.set_data(saved.entries(), saved.boot_snapshots(), "B")
    dialog._view.setCurrentIndex(2)
    dialog._search.setText("honey")
    dialog.set_data(saved.entries(), saved.boot_snapshots(), "B", "disk full")
    assert dialog._view.currentIndex() == 2
    assert dialog._search.text() == "honey"
    assert dialog._table.topLevelItemCount() == 1
    assert dialog._table.currentItem().text(4) == "Last seen"
    assert "disk full" in dialog._status.text()
    assert "Last successful save" in dialog._status.text()
    assert "/work/honey" in dialog._details.toPlainText()
    dialog.close()


def test_recording_failure_keeps_history_and_next_scan_recovers(app, saved):
    fake = SimpleNamespace(
        _recovery_store=saved, _recovery_error="", _recovery_entries=[],
        _recovery_boots=[], _recovery_dialog=TerminalRecoveryDialog(),
        _tabs_panel=SimpleNamespace(_recovery_button=QPushButton()),
    )
    with patch("claude_widget.scan_terminals", side_effect=OSError("proc unavailable")), patch("claude_widget.log_line"):
        ClaudeWidget._refresh_terminal_recovery(fake)
    assert len(fake._recovery_entries) == 3
    assert "recording error" in fake._tabs_panel._recovery_button.text()
    assert saved.boot_snapshots()[0]["captured"] == 200
    with patch("claude_widget.scan_terminals", return_value=[record(boot="B")]), patch("claude_widget.log_line"):
        ClaudeWidget._refresh_terminal_recovery(fake)
    assert fake._recovery_error == ""
    assert "recovery · 1" in fake._tabs_panel._recovery_button.text()
    assert "Recording ·" in fake._recovery_dialog._status.text()
    fake._recovery_dialog.close()


def test_unwritable_store_does_not_crash_widget_and_retries(app):
    fake = SimpleNamespace(
        _recovery_store=None, _recovery_error="", _recovery_entries=[],
        _recovery_boots=[], _recovery_dialog=None,
        _tabs_panel=SimpleNamespace(_recovery_button=QPushButton()),
    )
    with patch("claude_widget.TerminalRecoveryStore", side_effect=OSError("permission denied")) as factory, patch("claude_widget.log_line"):
        ClaudeWidget._refresh_terminal_recovery(fake)
        ClaudeWidget._refresh_terminal_recovery(fake)
    assert factory.call_count == 2
    assert "recording error" in fake._tabs_panel._recovery_button.text()
    assert "permission denied" in fake._tabs_panel._recovery_button.toolTip()


def test_tray_hide_hides_modeless_recovery_dialog(app):
    parent = QWidget()
    dialog = TerminalRecoveryDialog(parent)
    parent.show()
    dialog.show()
    fake = SimpleNamespace(_tray=object(), _recovery_dialog=dialog,
                           _hide_tabs_panel=Mock(), _restore_sliver=QWidget(),
                           hide=parent.hide)
    assert dialog.isVisible()
    ClaudeWidget.hide_to_tray(fake)
    assert not dialog.isVisible()
    assert not parent.isVisible()
    parent.close()
