from datetime import date
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

import pytest

from smart_todos import (
    InboxStore,
    MAX_TODO_BYTES,
    TodoItem,
    discover_todo_files,
    normalize_task_text,
    open_source_item,
    parse_todos,
    scan_todos,
    source_open_command,
)
import smart_todos


TODAY = date(2026, 7, 31)


def write_todo(path: Path, text: str = "- [ ] Do the work\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_todos_keeps_heading_path_and_only_explicit_due_dates():
    text = (
        "# Product\n"
        "## P0 Launch\n"
        "- [ ] Ship live check due: 2026-08-02 "
        "<!-- claude-indicator:id=abc -->\n"
        "- [ ] Review evidence from 2026-07-20\n"
    )

    items = parse_todos(text, Path("/work/alpha/TODO.md"), "alpha", TODAY)

    assert items[0].heading == "Product > P0 Launch"
    assert items[0].due_date == date(2026, 8, 2)
    assert items[0].managed_id is None
    assert items[0].text == "Ship live check due: 2026-08-02"
    assert items[1].due_date is None


def test_parse_todos_strips_display_markdown_and_preserves_completed_state():
    text = "# Weekly\n* [x] **Verify** `live` [guide](https://example.test)\n"

    item = parse_todos(text, Path("/work/alpha/TODO.md"), "alpha", TODAY)[0]

    assert item.text == "Verify live guide"
    assert item.completed is True
    assert item.line == 2


def test_discovery_is_bounded_and_skips_hidden_build_cache_and_worktree_paths(tmp_path):
    root = tmp_path / "workspaces"
    included = write_todo(root / "project" / "one" / "two" / "three" / "TODO.md")
    depth_four = write_todo(
        root / "project" / "one" / "two" / "three" / "four" / "TODO.md"
    )
    skipped = [
        write_todo(root / "project" / ".hidden" / "TODO.md"),
        write_todo(root / "project" / "build" / "TODO.md"),
        write_todo(root / "project" / ".pytest_cache" / "TODO.md"),
        write_todo(root / "project" / ".worktrees" / "TODO.md"),
    ]

    discovered = discover_todo_files((root,))

    assert included.resolve() in discovered
    assert depth_four.resolve() not in discovered
    assert not set(path.resolve() for path in skipped).intersection(discovered)


def test_discovery_deduplicates_resolved_paths(tmp_path):
    root = tmp_path / "workspaces"
    target = write_todo(root / "project" / "TODO.md")
    alias = root / "alias" / "TODO.md"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(target)

    discovered = discover_todo_files((root, root))

    assert discovered == (target.resolve(),)


def test_scan_rejects_symlink_todos_that_escape_the_workspace_root(tmp_path):
    root = tmp_path / "workspaces"
    home_todo = write_todo(tmp_path / "home" / "TODO.md", "# TODO\n")
    outside = write_todo(
        tmp_path / "outside" / "TODO.md",
        "- [ ] Do not read this escaped task\n",
    )
    escaped = root / "project" / "TODO.md"
    escaped.parent.mkdir(parents=True)
    escaped.symlink_to(outside)

    result = scan_todos(home_todo, (root,), today=TODAY)

    assert result.items == ()
    assert result.scanned_files == 1
    assert result.warnings == (f"Skipped symlink TODO file: {escaped}",)


def test_scan_warns_for_each_unavailable_workspace_root(tmp_path):
    home_todo = write_todo(tmp_path / "home" / "TODO.md", "# TODO\n")
    missing_root = tmp_path / "missing-workspace"
    non_directory_root = write_todo(tmp_path / "not-a-workspace", "not a directory\n")

    result = scan_todos(
        home_todo,
        (missing_root, non_directory_root),
        today=TODAY,
    )

    assert result.warnings == (
        f"Skipped unavailable workspace root: {missing_root}",
        f"Skipped unavailable workspace root: {non_directory_root}",
    )


def test_scan_skips_symlink_directories_silently_but_keeps_safety_warnings(tmp_path):
    root = tmp_path / "workspaces"
    home_todo = write_todo(tmp_path / "home" / "TODO.md", "# TODO\n")
    external_library = tmp_path / "external-library"
    write_todo(external_library / "TODO.md", "- [ ] Must not follow library link\n")
    library_link = root / "project" / "env" / "lib64"
    library_link.parent.mkdir(parents=True)
    library_link.symlink_to(external_library, target_is_directory=True)

    external_todo = write_todo(
        tmp_path / "external-todo" / "TODO.md",
        "- [ ] Must not follow TODO link\n",
    )
    todo_link = root / "linked-project" / "TODO.md"
    todo_link.parent.mkdir(parents=True)
    todo_link.symlink_to(external_todo)
    fifo_todo = root / "fifo-project" / "TODO.md"
    fifo_todo.parent.mkdir(parents=True)
    os.mkfifo(fifo_todo)
    missing_root = tmp_path / "missing-workspace"

    result = scan_todos(home_todo, (root, missing_root), today=TODAY)

    assert result.items == ()
    assert set(result.warnings) == {
        f"Skipped symlink TODO file: {todo_link}",
        f"Skipped special TODO file: {fifo_todo.resolve()}",
        f"Skipped unavailable workspace root: {missing_root}",
    }


def test_scan_skips_oversized_file_without_aborting_and_includes_home_once(tmp_path):
    root = tmp_path / "workspaces"
    home_todo = write_todo(root / "home" / "TODO.md", "- [ ] Overall inbox task\n")
    good = write_todo(root / "project" / "TODO.md", "- [ ] Project task\n")
    huge = root / "oversized" / "TODO.md"
    huge.parent.mkdir(parents=True)
    huge.write_bytes(b"x" * (MAX_TODO_BYTES + 1))

    result = scan_todos(home_todo, (root,), today=TODAY)

    assert [item.text for item in result.items] == ["Overall inbox task", "Project task"]
    assert result.scanned_files == 2
    assert result.warnings == (f"Skipped oversized TODO file: {huge.resolve()}",)
    assert good.resolve() in discover_todo_files((root,))


def test_scan_assigns_managed_ownership_only_inside_the_exact_home_inbox(tmp_path):
    root = tmp_path / "workspaces"
    home_todo = write_todo(
        tmp_path / "home" / "TODO.md",
        (
            "# TODO\n"
            "- [ ] Outside home collision <!-- claude-indicator:id=shared-id -->\n"
            "- [x] Outside home completed <!-- claude-indicator:id=outside-done -->\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "## Indicator Inbox\n\n"
            "- [ ] Owned home task <!-- claude-indicator:id=shared-id -->\n"
            "- [x] Owned completed task <!-- claude-indicator:id=owned-done -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
    )
    write_todo(
        root / "project" / "TODO.md",
        (
            "<!-- claude-indicator:inbox:start -->\n"
            "- [ ] Project collision <!-- claude-indicator:id=shared-id -->\n"
            "- [x] Project completed <!-- claude-indicator:id=project-done -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
    )

    result = scan_todos(home_todo, (root,), today=TODAY)
    by_text = {item.text: item for item in result.items}

    assert by_text["Owned home task"].managed_id == "shared-id"
    assert by_text["Owned completed task"].managed_id == "owned-done"
    assert by_text["Outside home collision"].managed_id is None
    assert by_text["Outside home completed"].managed_id is None
    assert by_text["Project collision"].managed_id is None
    assert by_text["Project completed"].managed_id is None


def make_item(
    text: str,
    *,
    heading: str = "",
    project: str = "alpha",
    due_date: date | None = None,
    completed: bool = False,
) -> TodoItem:
    return TodoItem(
        id=text,
        text=text,
        completed=completed,
        source_path=Path(f"/work/{project}/TODO.md"),
        line=1,
        heading=heading,
        project=project,
        due_date=due_date,
    )


def test_rank_item_applies_literal_scores_and_reasons_in_priority_order():
    cases = [
        (
            make_item("Deploy the launch", heading="P0", due_date=date(2026, 7, 30)),
            115,
            "critical",
            (
                "overdue by 1 day",
                "critical priority signal",
                "open task needs attention",
            ),
        ),
        (
            make_item("P1 revenue customer work"),
            50,
            "normal",
            ("revenue or customer impact", "open task needs attention"),
        ),
        (
            make_item("Review subscription billing cost"),
            45,
            "normal",
            ("billing or cost exposure", "open task needs attention"),
        ),
        (
            make_item("Verify production GSC smoke"),
            38,
            "normal",
            ("production verification work", "open task needs attention"),
        ),
        (
            make_item("Inbox task", project="Overall"),
            28,
            "normal",
            ("captured in overall inbox", "open task needs attention"),
        ),
    ]

    for item, score, urgency, reasons in cases:
        ranked = smart_todos.rank_item(item, TODAY)
        assert ranked.score == score
        assert ranked.urgency == urgency
        assert ranked.why_now == reasons


def test_rank_item_marks_explicit_and_future_gates_waiting_but_not_same_day_gate():
    held = smart_todos.rank_item(make_item("Hold until owner action"), TODAY)
    future_gate = smart_todos.rank_item(
        make_item("On or after 2026-08-22 evaluate GSC"), TODAY
    )
    no_earlier = smart_todos.rank_item(
        make_item("No earlier than 2026-08-03 verify live status"), TODAY
    )
    same_day = smart_todos.rank_item(
        make_item("On or after 2026-07-31 evaluate GSC"), TODAY
    )

    assert held.waiting is True
    assert held.tags == ("waiting",)
    assert held.why_now == ("explicitly waiting or on hold", "open task needs attention")
    assert future_gate.waiting is True
    assert future_gate.urgency == "waiting"
    assert "gated until 2026-08-22" in future_gate.why_now
    assert no_earlier.waiting is True
    assert "gated until 2026-08-03" in no_earlier.why_now
    assert same_day.waiting is False


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("blocked-by-owner before deploy", "explicitly waiting or on hold"),
        ("Only after 2026-08-04 review production", "gated until 2026-08-04"),
        ("Until 2026-08-05 launch", "gated until 2026-08-05"),
    ],
)
def test_rank_item_recognizes_documented_and_common_waiting_forms(text, reason):
    ranked = smart_todos.rank_item(make_item(text), TODAY)

    assert ranked.waiting is True
    assert ranked.urgency == "waiting"
    assert ranked.tags == ("waiting",)
    assert reason in ranked.why_now


@pytest.mark.parametrize(
    "text",
    ["Only after 2026-07-31 review production", "Until 2026-07-31 launch"],
)
def test_dated_waiting_forms_become_actionable_on_the_gate_date(text):
    ranked = smart_todos.rank_item(make_item(text), TODAY)

    assert ranked.waiting is False


def test_rank_item_scores_due_dates_and_completed_items_without_promoting_completion():
    tomorrow = smart_todos.rank_item(
        make_item("Tomorrow", due_date=date(2026, 8, 1)), TODAY
    )
    later = smart_todos.rank_item(
        make_item("Later", due_date=date(2026, 8, 3)), TODAY
    )
    completed = smart_todos.rank_item(
        make_item("P0 deploy", completed=True), TODAY
    )

    assert tomorrow.score == 40
    assert tomorrow.why_now == ("due tomorrow", "open task needs attention")
    assert later.score == 31
    assert later.why_now == ("due in 3 days", "open task needs attention")
    assert completed.score == 0
    assert completed.urgency == "completed"
    assert completed.why_now == ()


def test_rank_item_explains_the_generic_open_task_base_score():
    ranked = smart_todos.rank_item(make_item("Read the next task"), TODAY)

    assert ranked.score == 20
    assert ranked.why_now == ("open task needs attention",)


def test_future_gate_reason_survives_four_weighted_signals_and_reason_cap():
    ranked = smart_todos.rank_item(
        make_item(
            "P0 P1 billing verify production on or after 2026-08-22"
        ),
        TODAY,
    )

    assert ranked.waiting is True
    assert len(ranked.why_now) == 4
    assert ranked.why_now[0] == "gated until 2026-08-22"


@pytest.mark.parametrize(
    "text",
    ["Wait for provider evidence", "Blocked by owner action", "Sam: review this"],
)
def test_rank_item_marks_each_explicit_waiting_variant(text):
    ranked = smart_todos.rank_item(make_item(text), TODAY)

    assert ranked.waiting is True
    assert ranked.urgency == "waiting"
    assert ranked.tags == ("waiting",)
    assert "explicitly waiting or on hold" in ranked.why_now


def test_rank_item_explains_due_today_score():
    ranked = smart_todos.rank_item(
        make_item("Prepare release", due_date=TODAY), TODAY
    )

    assert ranked.score == 48
    assert ranked.why_now == ("due today", "open task needs attention")


def test_scan_sorts_actionable_before_waiting_and_completed_then_by_score(tmp_path):
    root = tmp_path / "workspaces"
    home_todo = write_todo(
        root / "home" / "TODO.md",
        "- [ ] P0 launch deploy\n- [ ] P0 hold for owner action\n- [x] P0 done\n",
    )
    write_todo(root / "beta" / "TODO.md", "- [ ] P1 revenue due: 2026-07-31\n")

    result = scan_todos(home_todo, (root,), today=TODAY)

    assert [item.text for item in result.items] == [
        "P1 revenue due: 2026-07-31",
        "P0 launch deploy",
        "P0 hold for owner action",
        "P0 done",
    ]


def test_inbox_add_initializes_missing_file_with_a_managed_section(tmp_path):
    path = tmp_path / "TODO.md"

    managed_id = InboxStore(path).add("Capture this task")

    assert path.read_text(encoding="utf-8") == (
        "# TODO\n\n"
        "<!-- claude-indicator:inbox:start -->\n"
        "## Indicator Inbox\n\n"
        f"- [ ] Capture this task <!-- claude-indicator:id={managed_id} -->\n"
        "<!-- claude-indicator:inbox:end -->\n"
    )


def test_inbox_add_appends_section_after_the_entire_existing_prefix(tmp_path):
    path = tmp_path / "TODO.md"
    original_prefix = "# Existing TODO\n\n- [ ] Preserve this project task\n"
    path.write_text(original_prefix, encoding="utf-8")

    InboxStore(path).add("Inbox task")

    assert path.read_text(encoding="utf-8").startswith(
        original_prefix
        + "\n<!-- claude-indicator:inbox:start -->\n## Indicator Inbox\n\n"
    )


def test_normalize_task_text_flattens_input_and_removes_markdown_control_syntax():
    assert normalize_task_text(
        "  - [x]  Finish\r\n  the report <!-- ignored metadata -->  "
    ) == "Finish the report"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (" \n\t ", "Enter a task before adding it."),
        ("x" * 501, "Tasks must be 500 characters or fewer."),
    ],
)
def test_normalize_task_text_rejects_invalid_task_copy(text, message):
    with pytest.raises(ValueError, match=message):
        normalize_task_text(text)


def test_inbox_add_serializes_due_date_and_uses_unique_uuid4_ids(tmp_path):
    path = tmp_path / "TODO.md"
    store = InboxStore(path)

    first = store.add("First", due_date=date(2026, 8, 2))
    second = store.add("Second")
    text = path.read_text(encoding="utf-8")

    assert first != second
    assert uuid.UUID(first).version == 4
    assert uuid.UUID(second).version == 4
    assert f"- [ ] First due: 2026-08-02 <!-- claude-indicator:id={first} -->" in text
    assert f"- [ ] Second <!-- claude-indicator:id={second} -->" in text


def test_inbox_add_rereads_the_current_file_before_mutating(tmp_path):
    path = tmp_path / "TODO.md"
    store = InboxStore(path)
    first = store.add("First")
    with path.open("a", encoding="utf-8") as todo_file:
        todo_file.write("\n## External edit\n- [ ] Keep this edit\n")

    second = store.add("Second")
    text = path.read_text(encoding="utf-8")

    assert f"claude-indicator:id={first}" in text
    assert f"claude-indicator:id={second}" in text
    assert text.endswith("\n## External edit\n- [ ] Keep this edit\n")


def test_inbox_add_preserves_the_existing_file_mode(tmp_path):
    path = write_todo(tmp_path / "TODO.md", "# TODO\n")
    path.chmod(0o640)

    InboxStore(path).add("Keep permissions")

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_inbox_add_preserves_unrelated_crlf_prefix_and_suffix_byte_for_byte(tmp_path):
    path = tmp_path / "TODO.md"
    prefix = b"# Existing\r\n\r\n- [ ] Prefix task\r\n"
    managed = (
        b"<!-- claude-indicator:inbox:start -->\r\n"
        b"## Indicator Inbox\r\n\r\n"
        b"<!-- claude-indicator:inbox:end -->\r\n"
    )
    suffix = b"\r\n## Tail\r\n- [ ] Suffix task\r\n"
    before = prefix + managed + suffix
    path.write_bytes(before)

    InboxStore(path).add("CRLF inbox task")

    after = path.read_bytes()
    start = before.index(b"<!-- claude-indicator:inbox:start -->")
    end = before.index(b"<!-- claude-indicator:inbox:end -->")
    after_end = after.index(b"<!-- claude-indicator:inbox:end -->")
    assert after[:start] == before[:start]
    assert after[after_end:] == before[end:]


def test_complete_changes_only_the_exact_managed_id(tmp_path):
    path = tmp_path / "TODO.md"
    store = InboxStore(path)
    first = store.add("First")
    second = store.add("Second")

    store.complete(second)

    text = path.read_text(encoding="utf-8")
    assert f"- [ ] First <!-- claude-indicator:id={first} -->" in text
    assert f"- [x] Second <!-- claude-indicator:id={second} -->" in text


def test_complete_preserves_all_other_crlf_bytes(tmp_path):
    path = tmp_path / "TODO.md"
    before = (
        b"# Existing\r\n- [ ] Prefix\r\n"
        b"<!-- claude-indicator:inbox:start -->\r\n"
        b"## Indicator Inbox\r\n\r\n"
        b"- [ ] Managed <!-- claude-indicator:id=managed-1 -->\r\n"
        b"<!-- claude-indicator:inbox:end -->\r\n"
        b"## Tail\r\n- [ ] Suffix\r\n"
    )
    path.write_bytes(before)

    InboxStore(path).complete("managed-1")

    assert path.read_bytes() == before.replace(b"- [ ] Managed", b"- [x] Managed", 1)


def test_complete_rejects_an_id_outside_the_managed_inbox_without_changes(tmp_path):
    path = write_todo(
        tmp_path / "TODO.md",
        "# TODO\n- [ ] Project task <!-- claude-indicator:id=project-entry -->\n",
    )
    before = path.read_bytes()

    with pytest.raises(ValueError, match="Task is not managed by the Indicator Inbox."):
        InboxStore(path).complete("project-entry")

    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "contents",
    [
        (
            "<!-- claude-indicator:inbox:start -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
        (
            "<!-- claude-indicator:inbox:end -->\n"
            "<!-- claude-indicator:inbox:start -->\n"
        ),
        "<!-- claude-indicator:inbox:start -->\n",
        "<!-- claude-indicator:inbox:end -->\n",
        (
            "<!-- claude-indicator:inbox:start -->\n"
            "<!-- claude-indicator:inbox:start -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
            "<!-- claude-indicator:inbox:end -->\n"
        ),
    ],
    ids=["duplicate", "reversed", "start-only", "end-only", "nested"],
)
def test_inbox_rejects_corrupt_marker_boundaries_without_changing_bytes(tmp_path, contents):
    path = write_todo(tmp_path / "TODO.md", contents)
    before = path.read_bytes()

    with pytest.raises(
        ValueError,
        match="Indicator Inbox markers are incomplete or duplicated; no changes were written.",
    ):
        InboxStore(path).add("Do not write")

    assert path.read_bytes() == before


def test_inbox_add_leaves_the_destination_unchanged_until_os_replace(tmp_path, monkeypatch):
    path = write_todo(tmp_path / "TODO.md", "# TODO\n")
    before = path.read_text(encoding="utf-8")
    original_replace = smart_todos.os.replace
    observed = []

    def observing_replace(source, destination):
        observed.append((Path(source), Path(destination), path.read_text(encoding="utf-8")))
        original_replace(source, destination)

    monkeypatch.setattr(smart_todos.os, "replace", observing_replace)

    InboxStore(path).add("Atomic task")

    assert observed[0][1] == path
    assert observed[0][2] == before
    assert "Atomic task" in path.read_text(encoding="utf-8")


def finished_item(
    *,
    managed_id: str | None = None,
    text: str = "Finish private release",
    line: int = 8,
    source_path: Path = Path("/work/alpha/TODO.md"),
    heading: str = "Release > Checks",
) -> TodoItem:
    return TodoItem(
        id=f"{source_path}:{line}",
        text=text,
        completed=False,
        source_path=source_path,
        line=line,
        heading=heading,
        project="alpha",
        managed_id=managed_id,
    )


def test_finished_key_uses_the_literal_managed_id_without_task_text():
    item = finished_item(managed_id="managed-42", text="Secret customer copy")

    assert smart_todos.todo_finished_key(item) == "managed:managed-42"


def test_finished_source_key_is_a_literal_sha256_of_stable_source_identity():
    item = finished_item()
    expected_digest = hashlib.sha256(
        b"/work/alpha/TODO.md\0Release > Checks\0Finish private release"
    ).hexdigest()

    assert smart_todos.todo_finished_key(item) == f"source:{expected_digest}"


def test_finished_source_key_survives_line_movement_but_changes_for_source_edits():
    original = finished_item(line=8)
    moved = finished_item(line=99)
    edited = finished_item(text="Finish revised private release", line=99)

    assert smart_todos.todo_finished_key(original) == smart_todos.todo_finished_key(moved)
    assert smart_todos.todo_finished_key(original) != smart_todos.todo_finished_key(edited)


def test_finished_store_writes_sorted_unique_keys_without_task_text(tmp_path):
    state_path = tmp_path / "state" / "finished.json"
    store = smart_todos.FinishedStore(state_path)
    source = finished_item(text="Private source wording")

    store.finish(source)
    store.finish(finished_item(managed_id="managed-z", text="Private managed wording"))
    store.finish(source)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "finished": sorted(payload["finished"]),
    }
    assert payload["finished"] == sorted(set(payload["finished"]))
    assert "Private source wording" not in state_path.read_text(encoding="utf-8")
    assert "Private managed wording" not in state_path.read_text(encoding="utf-8")
    assert store.read() == frozenset(payload["finished"])


def test_finished_store_rereads_current_state_before_each_write(tmp_path):
    state_path = tmp_path / "finished.json"
    state_path.write_text(
        json.dumps({"version": 1, "finished": ["managed:written-elsewhere"]}),
        encoding="utf-8",
    )

    smart_todos.FinishedStore(state_path).finish(finished_item(managed_id="managed:new"))

    assert json.loads(state_path.read_text(encoding="utf-8"))["finished"] == [
        "managed:managed:new",
        "managed:written-elsewhere",
    ]


def test_finished_store_creates_private_mode_and_preserves_existing_mode(tmp_path):
    created_path = tmp_path / "created.json"
    smart_todos.FinishedStore(created_path).finish(finished_item(managed_id="new"))
    assert stat.S_IMODE(created_path.stat().st_mode) == 0o600

    existing_path = tmp_path / "existing.json"
    existing_path.write_text('{"version": 1, "finished": []}', encoding="utf-8")
    existing_path.chmod(0o640)
    smart_todos.FinishedStore(existing_path).finish(finished_item(managed_id="existing"))
    assert stat.S_IMODE(existing_path.stat().st_mode) == 0o640


def test_finished_store_never_changes_source_todo_bytes(tmp_path):
    todo_path = tmp_path / "project" / "TODO.md"
    before = b"# Project\r\n- [ ] Preserve these bytes\r\n"
    todo_path.parent.mkdir()
    todo_path.write_bytes(before)

    smart_todos.FinishedStore(tmp_path / "finished.json").finish(
        finished_item(source_path=todo_path, text="Preserve these bytes")
    )

    assert todo_path.read_bytes() == before


def test_finished_store_leaves_destination_unchanged_until_os_replace(tmp_path, monkeypatch):
    state_path = tmp_path / "finished.json"
    before = b'{"version": 1, "finished": []}'
    state_path.write_bytes(before)
    original_replace = smart_todos.os.replace
    observed = []

    def observing_replace(source, destination):
        observed.append((Path(source), Path(destination), state_path.read_bytes()))
        original_replace(source, destination)

    monkeypatch.setattr(smart_todos.os, "replace", observing_replace)

    smart_todos.FinishedStore(state_path).finish(finished_item(managed_id="atomic"))

    assert observed == [(observed[0][0], state_path, before)]
    assert observed[0][0].parent == state_path.parent


@pytest.mark.parametrize(
    "contents",
    [
        b"{not json",
        b'{"version": 2, "finished": []}',
        b'{"version": 1, "finished": "not-a-list"}',
        b'{"version": 1, "finished": [42]}',
        b'{"version": 1, "finished": [], "unexpected": true}',
    ],
    ids=["malformed-json", "wrong-version", "wrong-schema", "non-string-key", "extra-key"],
)
def test_finished_store_rejects_invalid_state_without_mutation(tmp_path, contents):
    state_path = tmp_path / "finished.json"
    state_path.write_bytes(contents)
    before = state_path.read_bytes()

    with pytest.raises(ValueError, match="Finished state"):
        smart_todos.FinishedStore(state_path).finish(finished_item(managed_id="blocked"))

    assert state_path.read_bytes() == before


def test_finished_store_rejects_symlink_and_non_regular_paths_without_mutation(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"version": 1, "finished": []}', encoding="utf-8")
    symlink = tmp_path / "finished-link.json"
    symlink.symlink_to(target)
    target_before = target.read_bytes()

    with pytest.raises(ValueError, match="Finished state path must be a regular file"):
        smart_todos.FinishedStore(symlink).finish(finished_item(managed_id="blocked"))
    assert target.read_bytes() == target_before

    fifo_path = tmp_path / "finished.fifo"
    os.mkfifo(fifo_path)
    with pytest.raises(ValueError, match="Finished state path must be a regular file"):
        smart_todos.FinishedStore(fifo_path).finish(finished_item(managed_id="blocked"))


def source_item(*, completed=False):
    return TodoItem(
        id="source",
        text="Open source",
        completed=completed,
        source_path=Path("/tmp/Project TODO with spaces.md"),
        line=37,
        heading="",
        project="Overall",
    )


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (
            {"code": "/usr/bin/code", "codium": "/usr/bin/codium"},
            ["/usr/bin/code", "--goto", "/tmp/Project TODO with spaces.md:37"],
        ),
        (
            {"codium": "/usr/bin/codium"},
            ["/usr/bin/codium", "--goto", "/tmp/Project TODO with spaces.md:37"],
        ),
        (
            {"gedit": "/usr/bin/gedit"},
            ["/usr/bin/gedit", "+37", "/tmp/Project TODO with spaces.md"],
        ),
        (
            {"xdg-open": "/usr/bin/xdg-open"},
            ["/usr/bin/xdg-open", "/tmp/Project TODO with spaces.md"],
        ),
    ],
    ids=["code", "codium", "gedit", "xdg-open"],
)
def test_source_open_command_returns_literal_arguments_for_each_available_opener(
    available, expected
):
    assert source_open_command(source_item(), which=available.get) == expected


def test_source_open_command_navigates_completed_items_with_the_same_arguments():
    assert source_open_command(
        source_item(completed=True),
        which=lambda name: "/usr/bin/code" if name == "code" else None,
    ) == ["/usr/bin/code", "--goto", "/tmp/Project TODO with spaces.md:37"]


def test_source_open_command_rejects_missing_local_openers():
    with pytest.raises(RuntimeError, match="No local editor or file opener is available."):
        source_open_command(source_item(), which=lambda _name: None)


def test_open_source_item_passes_a_literal_command_without_shell_options(monkeypatch):
    command = ["/usr/bin/code", "--goto", "/tmp/Project TODO with spaces.md:37"]
    calls = []
    monkeypatch.setattr(smart_todos, "source_open_command", lambda _item: command)

    open_source_item(
        source_item(),
        popen=lambda received_command, **kwargs: calls.append((received_command, kwargs)),
    )

    assert calls == [(command, {"start_new_session": True})]
