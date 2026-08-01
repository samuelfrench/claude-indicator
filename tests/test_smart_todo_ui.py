from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

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


def make_dialog(
    tmp_path: Path,
    dialog_cleanup,
    *,
    home_text: str,
    projects=None,
    finished_store_path: Path | None = None,
    workflow_store_path: Path | None = None,
):
    home_todo = write_todo(tmp_path / "home" / "TODO.md", home_text)
    workspace = tmp_path / "workspace"
    for project, text in (projects or {}).items():
        write_todo(workspace / project / "TODO.md", text)
    dialog = SmartTodoDialog(
        home_todo_path=home_todo,
        workspace_roots=(workspace,),
        today_provider=lambda: TODAY,
        finished_store_path=finished_store_path or tmp_path / "finished.json",
        workflow_store_path=workflow_store_path or tmp_path / "workflow.json",
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


def selected_action_names(dialog: SmartTodoDialog):
    return [button.accessibleName() for button in dialog.workflow_action_buttons]


def accept_next_snooze_dialog(qapp, selected_date: date):
    def accept_dialog():
        dialog = qapp.activeModalWidget()
        assert isinstance(dialog, smart_todos.SnoozeUntilDialog)
        dialog.date_edit.setDate(QDate(selected_date.year, selected_date.month, selected_date.day))
        dialog.snooze_button.click()

    QTimer.singleShot(0, accept_dialog)


def test_initial_loading_state_disables_refresh(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")

    dialog.show_and_refresh()

    assert dialog.refresh_button.isEnabled() is False
    assert dialog.status_label.text() == "Scanning local TODO files…"
    assert dialog.loading_label.isVisible()
    wait_for_scan(dialog, qapp)


def test_focus_view_excludes_waiting_and_completed(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert visible_task_texts(dialog) == [
        "Overdue production check due: 2026-07-30",
        "P1 customer task",
    ]


def test_focus_view_excludes_hyphenated_owner_block_and_common_future_gates(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={
            "alpha": (
                "- [ ] P0 deploy blocked-by-owner\n"
                "- [ ] Only after 2026-08-03 verify production\n"
                "- [ ] Until 2026-08-04 launch\n"
                "- [ ] Actionable customer work\n"
            )
        },
    )

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert visible_task_texts(dialog) == ["Actionable customer work"]
    dialog.view_combo.setCurrentText("Waiting")
    assert set(visible_task_texts(dialog)) == {
        "P0 deploy blocked-by-owner",
        "Only after 2026-08-03 verify production",
        "Until 2026-08-04 launch",
    }


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


def test_860x680_long_real_todos_stay_compact_elided_accessible_and_actionable(
    qapp, tmp_path, dialog_cleanup, monkeypatch
):
    managed_text = "P0 production recovery " + " ".join(["managed detail"] * 130)
    long_token = "unbroken" * 18
    project_tasks = (
        "- [ ] Customer launch " + ("alpha context " * 125) + "\n"
        "- [ ] Billing follow-up " + long_token + (" beta context " * 120) + "\n"
        "- [ ] Verify deployment " + ("gamma context " * 210) + "\n"
    )
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "# TODO\n\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            f"- [ ] {managed_text} <!-- claude-indicator:id=long-managed -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={"alpha": project_tasks},
    )
    opened = []
    monkeypatch.setattr(smart_todos, "open_source_item", opened.append)
    dialog.resize(860, 680)

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    qapp.processEvents()

    assert (dialog.width(), dialog.height()) == (860, 680)
    assert dialog.scroll_area.horizontalScrollBar().maximum() == 0
    assert len(dialog.task_rows) == 4
    assert all(1500 <= len(row.item.text) <= 3000 for row in dialog.task_rows)
    assert any(long_token in row.item.text for row in dialog.task_rows)
    # One task-copy line, one metadata line, controls, and margins fit below 90px.
    assert all(0 < row.height() <= 90 for row in dialog.task_rows)
    for row in dialog.task_rows:
        assert row.text_label.text() != row.item.text
        assert row.text_label.text().endswith("…")
        assert row.text_label.toolTip() == row.item.text
        assert row.text_label.accessibleName() == row.item.text
        assert row.item.text in row.text_label.accessibleDescription()
        assert row.open_button.isVisible()
        assert row.open_button.geometry().right() <= row.width()

    managed_row = task_row(dialog, managed_text)
    QTest.mouseClick(managed_row, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert dialog.why_title_label.text() != managed_text
    assert dialog.why_title_label.text().endswith("…")
    assert dialog.why_title_label.height() <= 40
    assert dialog.why_title_label.toolTip() == managed_text
    assert dialog.why_title_label.accessibleName() == managed_text
    assert managed_text in dialog.why_title_label.accessibleDescription()

    managed_row.open_button.click()
    assert opened == [managed_row.item]
    assert managed_row.complete_button is not None
    assert managed_row.complete_button.isVisible()
    assert managed_row.complete_button.geometry().right() <= managed_row.width()
    managed_row.complete_button.click()
    wait_for_scan(dialog, qapp)

    assert f"- [x] {managed_text}" in dialog.home_todo_path.read_text(encoding="utf-8")
    assert managed_text not in visible_task_texts(dialog)
    assert dialog.scroll_area.horizontalScrollBar().maximum() == 0


def test_moving_selection_repolishes_task_copy(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog_with_fixture(tmp_path, dialog_cleanup)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    first, second = dialog.task_rows[:2]

    QTest.mouseClick(second, Qt.MouseButton.LeftButton)

    assert first.property("selected") is False
    assert second.property("selected") is True
    assert (
        first.text_label.palette().color(QPalette.ColorRole.WindowText).name()
        == "#b4b4c8"
    )
    assert (
        second.text_label.palette().color(QPalette.ColorRole.WindowText).name()
        == "#14141e"
    )


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


def test_active_rows_have_dismiss_but_completed_and_finished_rows_do_not(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "<!-- claude-indicator:inbox:start -->\n"
            "- [ ] Managed open <!-- claude-indicator:id=open-1 -->\n"
            "- [x] Managed completed <!-- claude-indicator:id=done-1 -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={"alpha": "- [ ] Project open\n- [ ] Waiting open until 2026-08-15\n"},
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.view_combo.setCurrentText("All open")
    assert all(row.dismiss_button is not None for row in dialog.task_rows)
    dialog.view_combo.setCurrentText("Completed inbox")
    assert task_row(dialog, "Managed completed").dismiss_button is None

    dialog.view_combo.setCurrentText("All open")
    task_row(dialog, "Project open").dismiss_button.click()
    dialog.view_combo.setCurrentText("Finished")
    finished_row = task_row(dialog, "Project open")
    assert finished_row.dismiss_button is None
    assert finished_row.complete_button is None
    assert finished_row.open_button.text() == "Open source"


@pytest.mark.parametrize(
    ("home_text", "projects", "task_text", "source_relative"),
    [
        (
            (
                "<!-- claude-indicator:inbox:start -->\n"
                "- [ ] Managed dismiss <!-- claude-indicator:id=managed-dismiss -->\n"
                "<!-- claude-indicator:inbox:end -->\n"
            ),
            {},
            "Managed dismiss",
            Path("home/TODO.md"),
        ),
        ("# TODO\n", {"alpha": "- [ ] Project dismiss\n"}, "Project dismiss", Path("workspace/alpha/TODO.md")),
    ],
    ids=["managed", "project"],
)
def test_dismiss_preserves_source_bytes_writes_state_and_moves_to_finished(
    qapp, tmp_path, dialog_cleanup, home_text, projects, task_text, source_relative
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=home_text,
        projects=projects,
    )
    source_path = tmp_path / source_relative
    before = source_path.read_bytes()
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    initial_summary = dialog.summary_label.text()

    task_row(dialog, task_text).dismiss_button.click()
    qapp.processEvents()

    assert source_path.read_bytes() == before
    assert task_text not in visible_task_texts(dialog)
    assert "0 focus" in dialog.summary_label.text()
    assert "0 open" in dialog.summary_label.text()
    assert dialog.summary_label.text() != initial_summary
    dialog.view_combo.setCurrentText("All open")
    assert task_text not in visible_task_texts(dialog)
    dialog.view_combo.setCurrentText("Finished")
    assert visible_task_texts(dialog) == [task_text]
    assert task_row(dialog, task_text).dismiss_button is None
    assert smart_todos.FinishedStore(dialog.finished_store_path).read()


def test_dismiss_immediately_finishes_every_row_with_the_same_source_key(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={
            "alpha": (
                "# Same heading\n"
                "- [ ] Duplicate source task\n"
                "- [ ] Duplicate source task\n"
            )
        },
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    assert visible_task_texts(dialog) == [
        "Duplicate source task",
        "Duplicate source task",
    ]

    dialog.task_rows[0].dismiss_button.click()

    assert visible_task_texts(dialog) == []
    assert "0 open" in dialog.summary_label.text()
    dialog.view_combo.setCurrentText("Finished")
    assert visible_task_texts(dialog) == [
        "Duplicate source task",
        "Duplicate source task",
    ]


def test_dismiss_immediately_finishes_every_row_with_the_same_managed_id(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "<!-- claude-indicator:inbox:start -->\n"
            "- [ ] First managed copy <!-- claude-indicator:id=duplicate-id -->\n"
            "- [ ] Second managed copy <!-- claude-indicator:id=duplicate-id -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    task_row(dialog, "First managed copy").dismiss_button.click()

    assert visible_task_texts(dialog) == []
    assert "0 open" in dialog.summary_label.text()
    dialog.view_combo.setCurrentText("Finished")
    assert visible_task_texts(dialog) == [
        "First managed copy",
        "Second managed copy",
    ]


def test_dismiss_write_failure_keeps_active_row_and_reports_inline_error(
    qapp, tmp_path, dialog_cleanup
):
    state_path = tmp_path / "finished.json"
    state_path.write_text("{malformed", encoding="utf-8")
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] Do not hide after failure\n",
        finished_store_path=state_path,
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    task_row(dialog, "Do not hide after failure").dismiss_button.click()

    assert "Finished state" in dialog.status_label.text()
    assert visible_task_texts(dialog) == ["Do not hide after failure"]
    assert "1 open" in dialog.summary_label.text()


def test_malformed_finished_state_warns_and_keeps_source_tasks_active(
    qapp, tmp_path, dialog_cleanup
):
    state_path = tmp_path / "finished.json"
    state_path.write_text('{"version": 2, "finished": []}', encoding="utf-8")
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] Keep active on warning\n",
        finished_store_path=state_path,
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert visible_task_texts(dialog) == ["Keep active on warning"]
    assert dialog.warning_label.isVisible()
    assert "Finished state" in dialog.warning_label.text()


def test_finished_selection_explains_command_center_state(qapp, tmp_path, dialog_cleanup):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] Explain finished state\n",
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    task_row(dialog, "Explain finished state").dismiss_button.click()
    dialog.view_combo.setCurrentText("Finished")
    QTest.mouseClick(task_row(dialog, "Explain finished state"), Qt.MouseButton.LeftButton)

    assert "finished in the command center" in dialog.why_reasons_label.text().lower()


def test_860x680_production_shape_keeps_dismiss_controls_without_horizontal_overflow(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "<!-- claude-indicator:inbox:start -->\n"
            "- [ ] Managed production row with enough context to need compact layout "
            "<!-- claude-indicator:id=wide-managed -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={
            "alpha": "- [ ] Project production row with enough context to need compact layout\n"
        },
    )
    dialog.resize(860, 680)
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    qapp.processEvents()

    assert dialog.scroll_area.horizontalScrollBar().maximum() == 0
    assert len(dialog.task_rows) == 2
    for row in dialog.task_rows:
        assert row.dismiss_button is not None
        assert row.dismiss_button.geometry().right() <= row.width()
        assert row.height() <= 90


def test_real_widgets_reject_project_home_outside_and_colliding_id_ownership(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "# TODO\n"
            "- [ ] Outside collision <!-- claude-indicator:id=shared-id -->\n"
            "- [x] Outside completed <!-- claude-indicator:id=outside-done -->\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            "- [ ] Owned collision <!-- claude-indicator:id=shared-id -->\n"
            "- [x] Owned completed <!-- claude-indicator:id=owned-done -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={
            "alpha": (
                "- [ ] Project collision <!-- claude-indicator:id=shared-id -->\n"
                "- [x] Project completed <!-- claude-indicator:id=project-done -->\n"
            )
        },
    )

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert task_row(dialog, "Owned collision").complete_button is not None
    assert task_row(dialog, "Outside collision").complete_button is None
    assert task_row(dialog, "Project collision").complete_button is None

    dialog.view_combo.setCurrentText("Completed inbox")
    assert visible_task_texts(dialog) == ["Owned completed"]


def test_completion_revalidates_managed_ownership_against_current_home_bytes(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            "- [ ] Initially owned <!-- claude-indicator:id=managed-1 -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    stale_complete_button = task_row(dialog, "Initially owned").complete_button
    assert stale_complete_button is not None

    current = (
        "- [ ] Moved outside <!-- claude-indicator:id=managed-1 -->\n"
        "<!-- claude-indicator:inbox:start -->\n"
        "## Indicator Inbox\n"
        "<!-- claude-indicator:inbox:end -->\n"
    ).encode()
    dialog.home_todo_path.write_bytes(current)

    stale_complete_button.click()

    assert dialog.home_todo_path.read_bytes() == current
    assert dialog.status_label.text() == "Task is not managed by the Indicator Inbox."


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


def test_real_scanner_failure_is_inline_and_dialog_stays_usable(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] Invalid calendar run due: 2026-08-01\n",
    )
    dialog.today_provider = object

    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert "unsupported operand type" in dialog.status_label.text()
    assert dialog.refresh_button.isEnabled()
    assert dialog.empty_label.text() == "TODO scan failed. Refresh to try again."
    assert dialog.empty_label.isVisible()


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


def test_action_rail_hides_without_selection_and_has_exact_accessible_actions(
    qapp, tmp_path, dialog_cleanup
):
    empty = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    empty.show_and_refresh()
    wait_for_scan(empty, qapp)

    assert empty.workflow_action_rail.isHidden()

    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "- [ ] Active customer work\n"},
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    assert selected_action_names(dialog) == [
        "Pin today",
        "Snooze task",
        "Copy task context",
    ]
    assert dialog.refresh_button.nextInFocusChain() is dialog.pin_button
    assert dialog.pin_button.nextInFocusChain() is dialog.snooze_button
    assert dialog.snooze_button.nextInFocusChain() is dialog.copy_context_button


def test_action_rail_projects_pinned_snoozed_finished_and_completed_states(
    qapp, tmp_path, dialog_cleanup
):
    workflow_path = tmp_path / "workflow.json"
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text=(
            "<!-- claude-indicator:inbox:start -->\n"
            "- [x] Completed inbox task <!-- claude-indicator:id=done -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        projects={"alpha": "- [ ] Active workflow task\n"},
        workflow_store_path=workflow_path,
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.pin_button.click()
    assert selected_action_names(dialog) == [
        "Unpin today",
        "Snooze task",
        "Copy task context",
    ]

    accept_next_snooze_dialog(qapp, TODAY + timedelta(days=1))
    dialog.snooze_button.click()
    dialog.view_combo.setCurrentText("All open")
    QTest.mouseClick(task_row(dialog, "Active workflow task"), Qt.MouseButton.LeftButton)
    assert selected_action_names(dialog) == ["Wake task now", "Copy task context"]

    dialog.view_combo.setCurrentText("Completed inbox")
    QTest.mouseClick(task_row(dialog, "Completed inbox task"), Qt.MouseButton.LeftButton)
    assert selected_action_names(dialog) == ["Copy task context"]

    dialog.view_combo.setCurrentText("All open")
    dialog.wake_button.click()
    task_row(dialog, "Active workflow task").dismiss_button.click()
    dialog.view_combo.setCurrentText("Finished")
    QTest.mouseClick(task_row(dialog, "Active workflow task"), Qt.MouseButton.LeftButton)
    assert selected_action_names(dialog) == [
        "Restore finished task",
        "Copy task context",
    ]
    dialog.restore_button.click()
    assert not smart_todos.FinishedStore(dialog.finished_store_path).read()
    assert all(not item.finished for item in dialog._all_items)


def test_snooze_until_dialog_defaults_shortcuts_validates_and_cancels(qapp):
    dialog = smart_todos.SnoozeUntilDialog(TODAY + timedelta(days=1), TODAY)

    assert dialog.date_edit.date().toPython() == TODAY + timedelta(days=1)
    assert dialog.tomorrow_button.accessibleName() == "Snooze until tomorrow"
    assert dialog.next_week_button.accessibleName() == "Snooze until next week"
    dialog.tomorrow_button.click()
    assert dialog.date_edit.date().toPython() == TODAY + timedelta(days=1)
    dialog.next_week_button.click()
    assert dialog.date_edit.date().toPython() == TODAY + timedelta(days=7)
    dialog.date_edit.setDate(QDate(TODAY.year, TODAY.month, TODAY.day))
    dialog.snooze_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.error_label.text() == "Choose a date after today."
    dialog.cancel_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected

    exact = smart_todos.SnoozeUntilDialog(TODAY + timedelta(days=1), TODAY)
    exact.date_edit.setDate(QDate(2026, 8, 3))
    exact.snooze_button.click()
    assert exact.result() == QDialog.DialogCode.Accepted
    assert exact.selected_date == date(2026, 8, 3)


def test_workflow_actions_persist_and_project_same_key_immediately(
    qapp, tmp_path, dialog_cleanup
):
    workflow_path = tmp_path / "workflow.json"
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "# Queue\n- [ ] Duplicate workflow item\n- [ ] Duplicate workflow item\n"},
        workflow_store_path=workflow_path,
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    dialog.pin_button.click()
    assert all(item.pinned_today for item in dialog._all_items)
    assert smart_todos.WorkflowStore(workflow_path).read().pinned_today
    dialog.unpin_button.click()
    assert not any(item.pinned_today for item in dialog._all_items)

    accept_next_snooze_dialog(qapp, TODAY + timedelta(days=7))
    dialog.snooze_button.click()
    assert {item.snoozed_until for item in dialog._all_items} == {TODAY + timedelta(days=7)}
    assert "0 focus" in dialog.summary_label.text()

    dialog.view_combo.setCurrentText("All open")
    QTest.mouseClick(dialog.task_rows[0], Qt.MouseButton.LeftButton)
    dialog.wake_button.click()
    assert all(item.snoozed_until is None for item in dialog._all_items)
    assert "2 focus" in dialog.summary_label.text()


def test_failed_workflow_and_restore_writes_preserve_rows_counts_and_selection(
    qapp, tmp_path, dialog_cleanup
):
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("{malformed", encoding="utf-8")
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "- [ ] Keep workflow item\n"},
        workflow_store_path=workflow_path,
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    before_summary = dialog.summary_label.text()
    selected_id = dialog._selected_item_id

    dialog.pin_button.click()

    assert dialog.status_label.text().startswith("Workflow state")
    assert visible_task_texts(dialog) == ["Keep workflow item"]
    assert dialog.summary_label.text() == before_summary
    assert dialog._selected_item_id == selected_id

    finished_path = tmp_path / "finished.json"
    finished_path.write_text("{malformed", encoding="utf-8")
    failed_restore = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "- [ ] Cannot restore\n"},
        finished_store_path=finished_path,
    )
    failed_restore.show_and_refresh()
    wait_for_scan(failed_restore, qapp)
    item = failed_restore._all_items[0]
    failed_restore._all_items = (smart_todos.replace(item, finished=True),)
    failed_restore.view_combo.setCurrentText("Finished")
    failed_restore._render_items()
    before_summary = failed_restore.summary_label.text()
    failed_restore.restore_button.click()

    assert failed_restore.status_label.text().startswith("Finished state")
    assert failed_restore._all_items[0].finished is True
    assert failed_restore.summary_label.text() == before_summary


def test_copy_context_writes_exact_plaintext_without_process_execution(
    qapp, tmp_path, dialog_cleanup, monkeypatch
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "# Delivery\n- [ ] P1 customer deploy due: 2026-08-02\n"},
    )
    monkeypatch.setattr(smart_todos.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("must not spawn"))
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)
    item = dialog._all_items[0]

    dialog.copy_context_button.click()

    assert qapp.clipboard().text() == (
        "Task: P1 customer deploy due: 2026-08-02\n"
        "Project: alpha\n"
        f"Source: {item.source_path.resolve()}:{item.line}\n"
        "Heading: Delivery\n"
        "Due: 2026-08-02\n"
        f"Urgency: {item.urgency} (score {item.score})\n"
        "Why now:\n"
        "- critical priority signal\n"
        "- revenue or customer impact\n"
        "- production verification work\n"
        "- due in 2 days"
    )


def test_repeated_refresh_while_active_coalesces_to_one_follow_up(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"bulk": "plain filler line\n" * 200_000},
    )
    summaries = []
    dialog.summary_changed.connect(lambda focus, overdue: summaries.append((focus, overdue)))
    dialog.refresh()
    first_worker = dialog.worker
    assert first_worker is not None
    deadline = time.monotonic() + 1
    while not first_worker.isRunning() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert first_worker.isRunning()

    dialog.home_todo_path.write_text("- [ ] Captured during scan\n", encoding="utf-8")
    dialog.refresh()
    dialog.refresh()
    assert dialog.refresh_pending is True

    wait_for_scan(dialog, qapp)

    assert len(summaries) == 2
    assert summaries[-1] == (1, 0)
    assert visible_task_texts(dialog) == ["Captured during scan"]


def test_summary_refresh_before_finished_keeps_specific_worker_ownership(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="- [ ] First task\n",
    )
    summaries = []

    def refresh_from_summary(focus, overdue):
        summaries.append((focus, overdue))
        if len(summaries) == 1:
            dialog.home_todo_path.write_text(
                "- [ ] First task\n- [ ] Second task\n",
                encoding="utf-8",
            )
            dialog.refresh()

    dialog.summary_changed.connect(refresh_from_summary)
    dialog.refresh()
    first_worker = dialog.worker
    assert first_worker is not None
    first_worker.finished.disconnect()
    assert first_worker.wait(2000)

    qapp.processEvents()
    assert dialog.worker is first_worker
    assert dialog.refresh_pending is True

    dialog._on_worker_finished(first_worker)
    follow_up_worker = dialog.worker
    assert follow_up_worker is not None
    assert follow_up_worker is not first_worker
    wait_for_scan(dialog, qapp)

    assert summaries == [(1, 0), (2, 0)]
    assert dialog.worker is None
    dialog.shutdown()
    assert dialog.worker is None


def test_fifo_todo_is_skipped_promptly_and_shutdown_remains_responsive(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    fifo_path = tmp_path / "workspace" / "fifo-project" / "TODO.md"
    fifo_path.parent.mkdir(parents=True)
    os.mkfifo(fifo_path)

    def release_legacy_blocking_reader():
        time.sleep(0.3)
        try:
            descriptor = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return
        try:
            os.write(descriptor, b"- [ ] Legacy FIFO task\n")
        finally:
            os.close(descriptor)

    writer = threading.Thread(target=release_legacy_blocking_reader)
    writer.start()
    before = time.monotonic()
    dialog.refresh()
    wait_for_scan(dialog, qapp, timeout_ms=1500)
    elapsed = time.monotonic() - before

    shutdown_before = time.monotonic()
    dialog.shutdown()
    shutdown_elapsed = time.monotonic() - shutdown_before
    writer.join(timeout=1)

    assert elapsed < 0.2
    assert shutdown_elapsed < 0.2
    assert f"Skipped special TODO file: {fifo_path.resolve()}" in dialog.warning_label.text()
    assert dialog.worker is None
    assert writer.is_alive() is False


def _perimeter_contains(widget, color: QColor) -> bool:
    image = widget.grab().toImage()
    width = image.width()
    height = image.height()
    coordinates = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    return any(image.pixelColor(x, y) == color for x, y in coordinates)


def test_keyboard_tab_order_has_visible_focus_for_interactive_controls(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(tmp_path, dialog_cleanup, home_text="# TODO\n")
    dialog.no_due_checkbox.setChecked(False)
    dialog.show()
    qapp.processEvents()
    dialog.task_input.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    gold = QColor("#D4A574")
    focus_order = (
        dialog.task_input,
        dialog.due_date_edit,
        dialog.no_due_checkbox,
        dialog.add_button,
        dialog.search_edit,
        dialog.project_combo,
        dialog.view_combo,
        dialog.reset_filters_button,
        dialog.refresh_button,
    )

    for index, widget in enumerate(focus_order):
        assert widget.hasFocus()
        assert _perimeter_contains(widget, gold)
        if index == len(focus_order) - 1:
            break
        for _ in range(4):
            QTest.keyClick(widget, Qt.Key.Key_Tab)
            qapp.processEvents()
            if not widget.hasFocus():
                break
        assert focus_order[index + 1].hasFocus()


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


def test_task_row_and_why_now_detail_expose_textual_accessible_urgency_band(
    qapp, tmp_path, dialog_cleanup
):
    dialog = make_dialog(
        tmp_path,
        dialog_cleanup,
        home_text="# TODO\n",
        projects={"alpha": "# P0\n- [ ] Deploy critical customer production fix\n"},
    )
    dialog.show_and_refresh()
    wait_for_scan(dialog, qapp)

    row = task_row(dialog, "Deploy critical customer production fix")
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)

    assert "CRITICAL URGENCY" in row.meta_label.text()
    assert "critical urgency" in row.accessibleName().lower()
    assert "Critical urgency" in dialog.why_meta_label.text()
    assert "critical urgency" in dialog.why_meta_label.accessibleName().lower()
