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
LOCATION_C = "location:" + "c" * 64
LOCATION_D = "location:" + "d" * 64
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
    assert payload["version"] == 1
    assert payload["pinned_today"] == [SOURCE_A, SOURCE_B]
    assert payload["snoozed"] == [
        {"key": SOURCE_A, "until": "2026-08-01"},
        {"key": SOURCE_B, "until": "2026-08-07"},
    ]
    assert [record["location"] for record in payload["observed"]] == [
        LOCATION_A, LOCATION_B
    ]
    assert [record["content"] for record in payload["observed"]] == [
        SOURCE_A, SOURCE_B
    ]
    assert sorted(record["sequence"] for record in payload["observed"]) == [0, 1]
    assert len({record["action"] for record in payload["observed"]}) == 2
    assert all(record["action"].startswith("source:") for record in payload["observed"])
    assert all(record["unchanged_since"] == "2026-07-01" for record in payload["observed"])
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
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[{"location":"location:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content":"source:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unchanged_since":"2026-07-01","action":"bad","sequence":0}]}',
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[{"location":"location:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content":"source:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unchanged_since":"2026-07-01","action":"source:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","sequence":true}]}',
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[{"location":"location:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content":"source:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unchanged_since":"2026-07-01","action":"source:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","sequence":0,"extra":1}]}',
        b'{"version":1,"pinned_today":[],"snoozed":[],"observed":[{"location":"managed:inbox-a","content":"managed:inbox-a","unchanged_since":"2026-07-01","action":"source:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","sequence":0}]}',
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


def test_workflow_store_keeps_legacy_v1_observations_readable_during_mutation(tmp_path):
    path = tmp_path / "workflow.json"
    path.write_text(
        (
            '{"version":1,"pinned_today":[],"snoozed":[],"observed":['
            '{"location":"' + LOCATION_A + '","content":"' + SOURCE_A
            + '","unchanged_since":"2026-07-01"}]}'
        ),
        encoding="utf-8",
    )
    store = smart_todo_workflow.WorkflowStore(path)

    store.pin(MANAGED_A)

    state = store.read()
    assert state.pinned_today == frozenset({MANAGED_A})
    assert state.observed[0].action == ""
    assert set(json.loads(path.read_text())["observed"][0]) == {
        "location", "content", "unchanged_since"
    }


@pytest.mark.parametrize(
    "replacement_keys",
    [
        (SOURCE_A, SOURCE_A),
        (SOURCE_B, SOURCE_A),
    ],
    ids=["duplicate", "unsorted"],
)
def test_legacy_expansion_rejects_noncanonical_replacement_keys_before_write(
    tmp_path, replacement_keys
):
    path = tmp_path / "workflow.json"
    before = (
        '{"version":1,"pinned_today":[],"snoozed":['
        '{"key":"managed:inbox-a","until":"2026-08-07"}],"observed":[]}'
    ).encode("utf-8")
    path.write_bytes(before)
    store = smart_todo_workflow.WorkflowStore(path)
    readable_before = store.read()

    with pytest.raises(ValueError, match="legacy-key expansion"):
        store.pin(
            SOURCE_A,
            legacy_key=MANAGED_A,
            replacement_keys=replacement_keys,
        )

    assert path.read_bytes() == before
    assert store.read() == readable_before


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

    assert len(state.observed) == 1
    assert state.observed[0].location == LOCATION_A
    assert state.observed[0].content == SOURCE_A
    assert state.observed[0].unchanged_since == date(2026, 7, 1)
    assert state.observed[0].action == tasks[SOURCE_A].action
    assert state.observed[0].sequence == 0
    assert tasks[SOURCE_A].change == ""


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

    assert tasks[SOURCE_A].location == LOCATION_B
    assert tasks[SOURCE_A].content == SOURCE_A
    assert tasks[SOURCE_A].unchanged_since == date(2026, 7, 9)
    assert tasks[SOURCE_A].change == ""


def test_reconcile_preserves_each_location_when_identical_content_has_two_copies(
    tmp_path,
):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.reconcile(
        (
            observation(LOCATION_A, SOURCE_A, date(2026, 7, 1)),
            observation(LOCATION_B, SOURCE_A, date(2026, 7, 5)),
        ),
        TODAY,
    )

    _state, tasks = store.reconcile(
        (
            observation(LOCATION_C, SOURCE_A, TODAY),
            observation(LOCATION_B, SOURCE_A, TODAY),
        ),
        TODAY,
    )

    assert tasks[LOCATION_C].unchanged_since == date(2026, 7, 1)
    assert tasks[LOCATION_C].change == ""
    assert tasks[LOCATION_B].unchanged_since == date(2026, 7, 5)
    assert tasks[LOCATION_B].change == ""


def test_reconcile_persists_opaque_identity_through_inferable_duplicate_group_edits(
    tmp_path,
):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    source_c = "source:" + "c" * 64
    initial = (
        observation(LOCATION_A, SOURCE_A),
        observation(LOCATION_B, SOURCE_B),
        observation(LOCATION_C, SOURCE_A),
        observation(LOCATION_D, source_c),
        observation("location:" + "e" * 64, SOURCE_A),
    )
    _state, tasks = store.reconcile(initial, TODAY)
    chosen_action = tasks[LOCATION_C].action

    inserted = (
        observation("location:" + "f" * 64, SOURCE_A),
        *initial,
    )
    _state, tasks = store.reconcile(inserted, date(2026, 8, 1))
    assert tasks[LOCATION_C].action == chosen_action
    assert sum(task.action == chosen_action for key, task in tasks.items() if key.startswith("location:")) == 1

    removed_peer = inserted[1:]
    _state, tasks = store.reconcile(removed_peer, date(2026, 8, 2))
    assert tasks[LOCATION_C].action == chosen_action

    reordered_peers = (
        observation(LOCATION_B, SOURCE_B),
        observation(LOCATION_C, SOURCE_A),
        observation(LOCATION_D, source_c),
        observation(LOCATION_A, SOURCE_A),
        observation("location:" + "e" * 64, SOURCE_A),
    )
    state, tasks = store.reconcile(reordered_peers, date(2026, 8, 3))
    assert tasks[LOCATION_C].action == chosen_action
    assert store.read() == state
    assert chosen_action.startswith("source:")
    assert len(chosen_action) == 71


def test_reconcile_never_transfers_identity_across_ambiguous_adjacent_duplicate_edit(
    tmp_path,
):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    _state, tasks = store.reconcile(
        (observation(LOCATION_A), observation(LOCATION_B)), TODAY
    )
    old_actions = {tasks[LOCATION_A].action, tasks[LOCATION_B].action}

    _state, tasks = store.reconcile(
        (
            observation(LOCATION_C),
            observation(LOCATION_A),
            observation(LOCATION_B),
        ),
        date(2026, 8, 1),
    )

    new_actions = {
        tasks[LOCATION_A].action,
        tasks[LOCATION_B].action,
        tasks[LOCATION_C].action,
    }
    assert old_actions.isdisjoint(new_actions)


def test_reconcile_marks_same_location_edit_and_unseen_content_new_for_one_scan(tmp_path):
    store = smart_todo_workflow.WorkflowStore(tmp_path / "workflow.json")
    store.reconcile((observation(LOCATION_A, SOURCE_A),), TODAY)

    _state, tasks = store.reconcile(
        (observation(LOCATION_A, SOURCE_B), observation(MANAGED_A, MANAGED_A)),
        date(2026, 8, 1),
    )

    assert tasks[SOURCE_B].location == LOCATION_A
    assert tasks[SOURCE_B].unchanged_since == date(2026, 8, 1)
    assert tasks[SOURCE_B].change == "changed"
    assert tasks[MANAGED_A].location == MANAGED_A
    assert tasks[MANAGED_A].unchanged_since == date(2026, 8, 1)
    assert tasks[MANAGED_A].change == "new"
    assert tasks[MANAGED_A].action == MANAGED_A


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
