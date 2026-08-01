from datetime import date
import json
import os
from pathlib import Path
import stat

import pytest

import smart_todo_workflow


TODAY = date(2026, 7, 31)
SOURCE_A = "source:" + "a" * 64
SOURCE_B = "source:" + "b" * 64
LOCATION_A = "location:" + "a" * 64
LOCATION_B = "location:" + "b" * 64
MANAGED_A = "managed:inbox-a"


def observation(location=LOCATION_A, content=SOURCE_A, modified=date(2026, 7, 1)):
    return smart_todo_workflow.TaskObservation(location, content, modified)


def test_workflow_store_creates_exact_empty_private_canonical_schema(tmp_path):
    path = tmp_path / "state" / "workflow.json"

    state = smart_todo_workflow.WorkflowStore(path).read()

    assert state == smart_todo_workflow.WorkflowState(frozenset(), (), ())
    assert not path.exists()
    smart_todo_workflow.WorkflowStore(path).pin(MANAGED_A)
    assert path.read_bytes() == b'{"version":1,"pinned_today":["managed:inbox-a"],"snoozed":[],"observed":[]}'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_workflow_store_writes_sorted_unique_records_without_task_text(tmp_path):
    path = tmp_path / "workflow.json"
    store = smart_todo_workflow.WorkflowStore(path)

    store.pin(SOURCE_B)
    store.pin(SOURCE_A)
    store.pin(SOURCE_A)
    store.snooze(SOURCE_B, date(2026, 8, 7))
    store.snooze(SOURCE_A, date(2026, 8, 1))
    store.snooze(SOURCE_A, date(2026, 8, 1))
    _state, _tasks = store.reconcile(
        (observation(LOCATION_B, SOURCE_B), observation(LOCATION_A, SOURCE_A)), TODAY
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "pinned_today": [SOURCE_A, SOURCE_B],
        "snoozed": [
            {"key": SOURCE_A, "until": "2026-08-01"},
            {"key": SOURCE_B, "until": "2026-08-07"},
        ],
        "observed": [
            {"location": LOCATION_A, "content": SOURCE_A, "unchanged_since": "2026-07-01"},
            {"location": LOCATION_B, "content": SOURCE_B, "unchanged_since": "2026-07-01"},
        ],
    }
    text = path.read_text(encoding="utf-8")
    assert "Private task text" not in text


@pytest.mark.parametrize(
    "contents",
    [
        b'{"version":1,"version":1,"pinned_today":[],"snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[],"extra":true}',
        b'{"version":1,"pinned_today":[],"snoozed":[]}',
        b'{"version":2,"pinned_today":[],"snoozed":[],"observed":[]}',
        b'{"version":true,"pinned_today":[],"snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":"managed:one","snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":["bad"],"snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":["managed:b","managed:a"],"snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":["managed:a","managed:a"],"snoozed":[],"observed":[]}',
        b'{"version":1,"pinned_today":[],"snoozed":[{"key":"managed:a","until":"2026-7-1"}],"observed":[]}',
        b'{"version":1,"pinned_today":[],"snoozed":[{"key":"managed:a","until":"2026-08-01"},{"key":"managed:a","until":"2026-08-01"}],"observed":[]}',
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[{"location":"location:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content":"source:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unchanged_since":"2026-07-01"},{"location":"location:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content":"source:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unchanged_since":"2026-07-01"}]}',
    ],
)
def test_workflow_store_rejects_noncanonical_or_invalid_state_without_mutation(
    tmp_path, contents
):
    path = tmp_path / "workflow.json"
    path.write_bytes(contents)

    with pytest.raises(ValueError, match="Workflow state"):
        smart_todo_workflow.WorkflowStore(path).read()

    assert path.read_bytes() == contents


def test_workflow_store_rejects_two_snooze_records_for_the_same_task_key(tmp_path):
    path = tmp_path / "workflow.json"
    contents = (
        '{"version":1,"pinned_today":[],"snoozed":['
        '{"key":"' + SOURCE_A + '","until":"2026-08-01"},'
        '{"key":"' + SOURCE_A + '","until":"2026-08-02"}'
        '],"observed":[]}'
    ).encode("utf-8")
    path.write_bytes(contents)

    with pytest.raises(ValueError, match="Workflow state"):
        smart_todo_workflow.WorkflowStore(path).read()

    assert path.read_bytes() == contents


def test_workflow_store_rejects_two_observed_records_for_one_location(tmp_path):
    path = tmp_path / "workflow.json"
    contents = (
        '{"version":1,"pinned_today":[],"snoozed":[],"observed":['
        '{"location":"' + LOCATION_A + '","content":"' + SOURCE_A
        + '","unchanged_since":"2026-07-01"},'
        '{"location":"' + LOCATION_A + '","content":"' + SOURCE_B
        + '","unchanged_since":"2026-07-02"}'
        ']}'
    ).encode("utf-8")
    path.write_bytes(contents)

    with pytest.raises(ValueError, match="Workflow state"):
        smart_todo_workflow.WorkflowStore(path).read()

    assert path.read_bytes() == contents


def test_workflow_store_rejects_symlink_and_fifo_paths(tmp_path):
    target = tmp_path / "target.json"
    target.write_bytes(b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[]}')
    link = tmp_path / "workflow-link.json"
    link.symlink_to(target)
    before = target.read_bytes()

    with pytest.raises(ValueError, match="regular file"):
        smart_todo_workflow.WorkflowStore(link).pin(MANAGED_A)
    assert target.read_bytes() == before

    fifo = tmp_path / "workflow.fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular file"):
        smart_todo_workflow.WorkflowStore(fifo).read()


def test_workflow_store_preserves_existing_mode_rereads_before_mutating_and_fsyncs(tmp_path, monkeypatch):
    path = tmp_path / "workflow.json"
    path.write_bytes(b'{"version":1,"pinned_today":["managed:outside"],"snoozed":[],"observed":[]}')
    path.chmod(0o640)
    fsync_calls = []
    real_fsync = smart_todo_workflow.os.fsync
    monkeypatch.setattr(smart_todo_workflow.os, "fsync", lambda fd: (fsync_calls.append(fd), real_fsync(fd))[1])

    store = smart_todo_workflow.WorkflowStore(path)
    store.pin(MANAGED_A)

    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert json.loads(path.read_text(encoding="utf-8"))["pinned_today"] == [MANAGED_A, "managed:outside"]
    assert fsync_calls


def test_workflow_store_keeps_destination_unchanged_until_final_replace(tmp_path, monkeypatch):
    path = tmp_path / "workflow.json"
    before = b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[]}'
    path.write_bytes(before)
    observed = []
    real_replace = smart_todo_workflow.os.replace

    def observe_replace(source, destination):
        observed.append((Path(source), Path(destination), path.read_bytes()))
        real_replace(source, destination)

    monkeypatch.setattr(smart_todo_workflow.os, "replace", observe_replace)
    smart_todo_workflow.WorkflowStore(path).pin(MANAGED_A)

    assert observed == [(observed[0][0], path, before)]
    assert observed[0][0].parent == path.parent


def test_reconcile_first_snapshot_seeds_source_date_and_returns_no_changes(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")

    state, tasks = store.reconcile((observation(modified=date(2026, 7, 1)),), TODAY)

    assert state.observed == (smart_todo_workflow.ObservedRecord(LOCATION_A, SOURCE_A, date(2026, 7, 1)),)
    assert tasks[SOURCE_A] == smart_todo_workflow.ObservedTask(LOCATION_A, SOURCE_A, date(2026, 7, 1), "")


def test_reconcile_keeps_same_location_content_unchanged_then_clears_change_label(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.reconcile((observation(),), TODAY)

    _state, tasks = store.reconcile((observation(),), date(2026, 8, 1))

    assert tasks[SOURCE_A].unchanged_since == date(2026, 7, 1)
    assert tasks[SOURCE_A].change == ""


def test_reconcile_recognizes_moved_content_with_oldest_matching_date(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.reconcile((observation(LOCATION_A, SOURCE_A, date(2026, 7, 9)),), TODAY)

    _state, tasks = store.reconcile((observation(LOCATION_B, SOURCE_A),), date(2026, 8, 1))

    assert tasks[SOURCE_A] == smart_todo_workflow.ObservedTask(LOCATION_B, SOURCE_A, date(2026, 7, 9), "")


def test_reconcile_marks_same_location_edit_and_unseen_content_new_for_one_scan(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.reconcile((observation(LOCATION_A, SOURCE_A),), TODAY)

    _state, tasks = store.reconcile(
        (observation(LOCATION_A, SOURCE_B), observation(MANAGED_A, MANAGED_A)),
        date(2026, 8, 1),
    )

    assert tasks[SOURCE_B] == smart_todo_workflow.ObservedTask(LOCATION_A, SOURCE_B, date(2026, 8, 1), "changed")
    assert tasks[MANAGED_A] == smart_todo_workflow.ObservedTask(MANAGED_A, MANAGED_A, date(2026, 8, 1), "new")


def test_reconcile_prunes_expired_snoozes_but_keeps_future_snoozes_and_missing_choices(tmp_path):
    path = tmp_path / "workflow.json"
    path.write_bytes(
        (
            '{"version":1,"pinned_today":["' + SOURCE_B
                + '"],"snoozed":[{"key":"' + SOURCE_A
                + '","until":"2026-08-01"},{"key":"' + SOURCE_B
                + '","until":"2026-07-31"}],"observed":[]}'
        ).encode("utf-8")
    )
    store = smart_todo_workflow.WorkflowStore(path)

    state, _tasks = store.reconcile((observation(),), TODAY)

    assert state.pinned_today == frozenset({SOURCE_B})
    assert state.snoozed == (smart_todo_workflow.SnoozeRecord(SOURCE_A, date(2026, 8, 1)),)


def test_workflow_store_unpin_wake_and_invalid_mutations_leave_state_valid(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.pin(MANAGED_A)
    store.snooze(MANAGED_A, date(2026, 8, 1))
    store.unpin(MANAGED_A)
    store.wake(MANAGED_A)

    assert store.read() == smart_todo_workflow.WorkflowState(frozenset(), (), ())
    with pytest.raises(ValueError, match="Workflow key"):
        store.pin("task text")
    with pytest.raises(ValueError, match="future"):
        store.snooze(MANAGED_A, TODAY)
