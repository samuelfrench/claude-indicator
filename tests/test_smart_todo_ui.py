from __future__ import annotations

from datetime import date
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import smart_todos
from smart_todos import MAX_TODO_BYTES, SmartTodoDialog


TODAY = date(2026, 7, 31)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dialog_cleanup():
    dialogs: list[SmartTodoDialog] = []
    yield dialogs
    for dialog in dialogs:
        dialog.shutdown()
        dialog.close()


def write_todo(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_dialog(tmp_path: Path, dialog_cleanup, *, home_text: str, projects=None):
    home_todo = write_todo(tmp_path / "home" / "TODO.md", home_text)
    workspace = tmp_path / "workspace"
    for project, text in (projects or {}).items():
        write_todo(workspace / project / "TODO.md", text)
    dialog = SmartTodoDialog(
        home_todo_path=home_todo,
        workspace_roots=(workspace,),
        today_provider=lambda: TODAY,
    )
    dialog_cleanup.append(dialog)
    return dialog


def make_dialog_with_fixture(tmp_path: Path, dialog_cleanup):
    return make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "# TODO\n\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            "- [x] Archived inbox note <!-- claude-indicator:id=done-1 -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={
            "alpha": (
                "# Delivery\n"
                "- [ ] Overdue production check due: 2026-07-30\n"
                "- [ ] Waiting deploy on or after 2026-08-15\n"
                "- [x] Completed project note\n"
            ),
            "beta": "# Customers\n- [ ] P1 customer task\n",
        },
    )


def wait_for_scan(dialog: SmartTodoDialog, qapp, timeout_ms: int = 4000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if dialog.worker is None and not dialog.refresh_pending:
            return
        QTest.qWait(10)
    pytest.fail("Smart TODO scan did not finish")


def visible_task_texts(dialog: SmartTodoDialog):
    return [row.item.text for row in dialog.task_rows]


def task_row(dialog: SmartTodoDialog, text: str):
    return next(row for row in dialog.task_rows if row.item.text == text)


def test_initial_loading_state_disables_refresh(qapp, tmp_path, dialog_cleanup, monkeypatch):
    release = threading.Event()
    real_scan = smart_todos.scan_todos

    def blocked_scan(*args, **kwargs):
        release.wait(timeout=2)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(smart_todos, "scan_todos", blocked_scan)
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")

    dialog.show_and_refresh()

    assert dialog.refresh_button.isEnabled() is False
    assert dialog.status_label.text() == "Scanning local TODO files…"
    assert dialog.loading_label.isVisible()
    release.set()
    wait_for_scan(dialog, qapp)


def test_focus_view_excludes_waiting_and_completed(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert visible_task_texts(dialog) == [
        "Overdue production check due: 2026-07-30",
        "P1 customer task",
    ]


def test_refresh_emits_full_summary_and_caps_rows(qapp, tmp_path, dialog_cleanup):
    task_lines = "".join(f"- [ ] Routine task {index:03d}\n" for index in range(260))
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n", projects={"bulk": task_lines})
    summaries = []
    dialog.summary_changed.connect(lambda focus, overdue: summaries.append((focus, overdue)))

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert summaries[-1] == (260, 0)
    assert "260 focus" in dialog.summary_label.text()
    assert len(dialog.task_rows) == 250
    assert dialog.render_limit_label.isVisible()


def test_each_view_has_literal_membership(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.view_combo.setCurrentText("All open")
    assert visible_task_texts(dialog) == [
        "Overdue production check due: 2026-07-30",
        "P1 customer task",
        "Waiting deploy on or after 2026-08-15",
    ]

    dialog.view_combo.setCurrentText("Waiting")
    assert visible_task_texts(dialog) == ["Waiting deploy on or after 2026-08-15"]

    dialog.view_combo.setCurrentText("Completed inbox")
    assert visible_task_texts(dialog) == ["Archived inbox note"]


def test_search_project_filter_and_reset(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.view_combo.setCurrentText("All open")
    dialog.search_edit.setText("OVERDUE")
    assert visible_task_texts(dialog) == ["Overdue production check due: 2026-07-30"]

    dialog.search_edit.clear()
    dialog.project_combo.setCurrentText("beta")
    assert visible_task_texts(dialog) == ["P1 customer task"]

    dialog.reset_filters_button.click()
    assert dialog.search_edit.text() == ""
    assert dialog.project_combo.currentText() == "All projects"
    assert dialog.view_combo.currentText() == "Focus"
    assert len(dialog.task_rows) == 2


def test_selection_updates_why_now_rail(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    selected = task_row(dialog, "P1 customer task")
    QTest.mouseClick(selected, Qt.MouseButton.LeftButton)

    assert selected.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert selected.property("selected") is True
    assert dialog.why_title_label.text() == "P1 customer task"
    assert "revenue or customer impact" in dialog.why_reasons_label.text()
    assert "beta" in dialog.why_meta_label.text()


def test_add_validation_failure_preserves_input_and_success_refreshes(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.task_input.setText("   ")
    dialog.add_button.click()
    assert dialog.status_label.text() == "Enter a task before adding it."

    dialog.task_input.setText("Capture customer follow-up")
    dialog.add_button.click()
    wait_for_scan(dialog, qapp)

    assert dialog.task_input.text() == ""
    assert "Capture customer follow-up" in visible_task_texts(dialog)
    assert "Capture customer follow-up" in dialog.home_todo_path.read_text(encoding="utf-8")


def test_add_write_failure_keeps_typed_task(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n<!-- claude-indicator:inbox:start -->\n",
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    dialog.task_input.setText("Do not lose this")

    dialog.add_button.click()

    assert dialog.task_input.text() == "Do not lose this"
    assert "markers are incomplete or duplicated" in dialog.status_label.text()


def test_completion_control_exists_only_for_open_managed_rows(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "# TODO\n\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            "- [ ] Managed open task <!-- claude-indicator:id=open-1 -->\n"
            "- [x] Managed done task <!-- claude-indicator:id=done-1 -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={"alpha": "- [ ] Read-only project task\n"},
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    managed = task_row(dialog, "Managed open task")
    project = task_row(dialog, "Read-only project task")
    assert managed.complete_button is not None
    assert project.complete_button is None

    managed.complete_button.click()
    wait_for_scan(dialog, qapp)

    assert "- [x] Managed open task" in dialog.home_todo_path.read_text(encoding="utf-8")
    assert "Managed open task" not in visible_task_texts(dialog)


def test_open_source_button_and_double_click_route_item(
    qapp, tmp_path, dialog_cleanup, monkeypatch
):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    opened = []
    monkeypatch.setattr(smart_todos, "open_source_item", opened.append)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    row = task_row(dialog, "P1 customer task")

    row.open_button.click()
    QTest.mouseDClick(row, Qt.MouseButton.LeftButton)

    assert opened == [row.item, row.item]


def test_open_source_failure_is_inline_and_dialog_stays_usable(
    qapp, tmp_path, dialog_cleanup, monkeypatch
):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)

    def fail_open(_item):
        raise RuntimeError("No editor available")

    monkeypatch.setattr(smart_todos, "open_source_item", fail_open)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    task_row(dialog, "P1 customer task").open_button.click()

    assert dialog.status_label.text() == "No editor available"
    assert dialog.refresh_button.isEnabled()


def test_warning_banner_and_empty_state(qapp, tmp_path, dialog_cleanup):
    home_path = tmp_path / "missing" / "TODO.md"
    dialog = SmartTodoDialog(
        home_todo_path=home_path,
        workspace_roots=(tmp_path / "nothing",),
        today_provider=lambda: TODAY,
    )
    dialog_cleanup.append(dialog)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert dialog.warning_label.isVisible()
    assert "Skipped unreadable TODO file" in dialog.warning_label.text()
    assert dialog.empty_label.isVisible()
    assert dialog.empty_label.text() == "No TODO items found. Add one above."


def test_oversized_warning_does_not_hide_other_results(qapp, tmp_path, dialog_cleanup):
    workspace = tmp_path / "workspace"
    huge = workspace / "huge" / "TODO.md"
    huge.parent.mkdir(parents=True)
    huge.write_bytes(b"x" * (MAX_TODO_BYTES + 1))
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] Visible overall task\n",
    )
    dialog.workspace_roots = (workspace,)

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert visible_task_texts(dialog) == ["Visible overall task"]
    assert str(huge.resolve()) in dialog.warning_label.text()


def test_repeated_refresh_while_active_coalesces_to_one_follow_up(
    qapp, tmp_path, dialog_cleanup, monkeypatch
):
    release = threading.Event()
    calls = []
    real_scan = smart_todos.scan_todos

    def controlled_scan(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            release.wait(timeout=2)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(smart_todos, "scan_todos", controlled_scan)
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    dialog.refresh()
    dialog.refresh()
    dialog.refresh()
    assert dialog.refresh_pending is True

    release.set()
    wait_for_scan(dialog, qapp)

    assert len(calls) == 2


def test_shutdown_waits_for_active_worker(qapp, tmp_path, dialog_cleanup, monkeypatch):
    release = threading.Event()
    started = threading.Event()
    real_scan = smart_todos.scan_todos

    def controlled_scan(*args, **kwargs):
        started.set()
        release.wait(timeout=2)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(smart_todos, "scan_todos", controlled_scan)
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    dialog.refresh()
    assert started.wait(timeout=1)
    threading.Timer(0.12, release.set).start()

    before = time.monotonic()
    dialog.shutdown()
    elapsed = time.monotonic() - before

    assert elapsed >= 0.1
    assert dialog.worker is None


def test_dialog_has_tool_flags_size_accessibility_and_exact_palette(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")

    assert dialog.windowFlags() & Qt.WindowType.Tool
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert dialog.minimumWidth() == 760
    assert dialog.minimumHeight() == 620
    assert dialog.task_input.accessibleName() == "New task"
    assert dialog.search_edit.accessibleName() == "Search tasks"
    for color in ("#14141E", "#20202D", "#D4A574", "#8B5CF6", "#F87171", "#B4B4C8"):
        assert color in dialog.styleSheet()
