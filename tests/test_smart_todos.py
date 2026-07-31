from datetime import date
from pathlib import Path

import pytest

from smart_todos import (
    MAX_TODO_BYTES,
    TodoItem,
    discover_todo_files,
    parse_todos,
    scan_todos,
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
    assert items[0].managed_id == "abc"
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
