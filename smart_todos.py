"""Local, bounded parsing and ranking for Markdown TODO files."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid


MAX_TODO_BYTES = 4 * 1024 * 1024
MAX_TODO_DEPTH = 3
MAX_VISIBLE_ITEMS = 250
IGNORED_DIRS = frozenset({
    ".git", ".worktrees", ".next", ".pytest_cache", ".venv", ".wrangler",
    "__pycache__", "build", "coverage", "dist", "node_modules",
    "playwright-report", "target", "test-results", "venv",
})
TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MANAGED_ID_RE = re.compile(r"<!--\s*claude-indicator:id=([0-9A-Za-z-]+)\s*-->\s*$")
INBOX_START_MARKER = "<!-- claude-indicator:inbox:start -->"
INBOX_END_MARKER = "<!-- claude-indicator:inbox:end -->"
INBOX_MARKER_ERROR = (
    "Indicator Inbox markers are incomplete or duplicated; no changes were written."
)
MAX_TASK_TEXT_LENGTH = 500
DUE_RE = re.compile(
    r"\b(?:due|by|on|target|date)\s*:?\s*(20\d{2}-\d{2}-\d{2})\b", re.I
)
SIGNALS = (
    (45, r"\bp0\b|highest|critical|urgent|immediate|blocker|launch|deploy", "critical priority signal"),
    (30, r"\bp1\b|revenue|money|growth|traffic|outreach|follow[ -]?up|customer|checkout", "revenue or customer impact"),
    (25, r"billing|paid|cost|subscription|charge", "billing or cost exposure"),
    (18, r"verify|validation|test|smoke|production|live|indexing|gsc|ga4", "production verification work"),
)
GATE_RE = re.compile(r"\b(?:on or after|no earlier than)\s+(20\d{2}-\d{2}-\d{2})\b", re.I)
WAITING_RE = re.compile(
    r"\bwaiting\b|wait for|\bhold\b|blocked by|owner action|\bsam\s*:", re.I
)


@dataclass(frozen=True)
class TodoItem:
    id: str
    text: str
    completed: bool
    source_path: Path
    line: int
    heading: str
    project: str
    due_date: date | None = None
    managed_id: str | None = None
    score: int = 0
    urgency: str = "normal"
    tags: tuple[str, ...] = ()
    why_now: tuple[str, ...] = ()
    waiting: bool = False


@dataclass(frozen=True)
class ScanResult:
    items: tuple[TodoItem, ...]
    warnings: tuple[str, ...]
    scanned_files: int
    generated_at: datetime


def normalize_task_text(text: str) -> str:
    """Normalize user-entered task copy into one safe Markdown line."""
    normalized = text.replace("\r", " ").replace("\n", " ")
    normalized = re.sub(r"<!--.*?-->", "", normalized)
    normalized = re.sub(r"^\s*(?:[-*+]\s+)?(?:\[[ xX]\]\s*)?", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ValueError("Enter a task before adding it.")
    if len(normalized) > MAX_TASK_TEXT_LENGTH:
        raise ValueError("Tasks must be 500 characters or fewer.")
    return normalized


class InboxStore:
    """Atomically mutate only the delimited local Indicator Inbox section."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def add(self, text: str, due_date: date | None = None) -> str:
        """Add one normalized task to the managed inbox and return its UUID4 ID."""
        task_text = normalize_task_text(text)
        managed_id = str(uuid.uuid4())
        due_suffix = f" due: {due_date.isoformat()}" if due_date else ""
        entry = (
            f"- [ ] {task_text}{due_suffix} "
            f"<!-- claude-indicator:id={managed_id} -->\n"
        )
        contents, mode = self._read_current()
        start, end = self._managed_bounds(contents)
        if start is None:
            updated = self._append_managed_section(contents, entry)
        else:
            updated = contents[:end] + entry + contents[end:]
        self._write_atomically(updated, mode)
        return managed_id

    def complete(self, managed_id: str) -> None:
        """Complete exactly one checkbox within the managed inbox section."""
        contents, mode = self._read_current()
        start, end = self._managed_bounds(contents)
        if start is None:
            raise ValueError("Task is not managed by the Indicator Inbox.")

        managed = contents[start:end]
        task_pattern = re.compile(
            r"^(\s*[-*]\s+\[)[ xX](\]\s+.*?<!--\s*claude-indicator:id="
            + re.escape(managed_id)
            + r"\s*-->[^\n]*)$",
            re.MULTILINE,
        )
        if len(task_pattern.findall(managed)) != 1:
            raise ValueError("Task is not managed by the Indicator Inbox.")
        updated_managed = task_pattern.sub(r"\1x\2", managed, count=1)
        self._write_atomically(contents[:start] + updated_managed + contents[end:], mode)

    def _read_current(self) -> tuple[str, int]:
        try:
            stat_result = self.path.stat()
        except FileNotFoundError:
            return "# TODO\n", 0o644
        return self.path.read_text(encoding="utf-8"), stat_result.st_mode & 0o7777

    @staticmethod
    def _managed_bounds(contents: str) -> tuple[int | None, int | None]:
        start_positions = [
            match.start()
            for match in re.finditer(re.escape(INBOX_START_MARKER), contents)
        ]
        end_positions = [
            match.start()
            for match in re.finditer(re.escape(INBOX_END_MARKER), contents)
        ]
        if not start_positions and not end_positions:
            return None, None
        if (
            len(start_positions) != 1
            or len(end_positions) != 1
            or start_positions[0] >= end_positions[0]
        ):
            raise ValueError(INBOX_MARKER_ERROR)
        return start_positions[0] + len(INBOX_START_MARKER), end_positions[0]

    @staticmethod
    def _append_managed_section(contents: str, entry: str) -> str:
        if contents.endswith("\n\n"):
            boundary = ""
        elif contents.endswith("\n"):
            boundary = "\n"
        else:
            boundary = "\n\n"
        return (
            f"{contents}{boundary}{INBOX_START_MARKER}\n"
            f"## Indicator Inbox\n\n{entry}{INBOX_END_MARKER}\n"
        )

    def _write_atomically(self, contents: str, mode: int) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(contents)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.chmod(temporary_path, mode)
            os.replace(temporary_path, self.path)
            temporary_path = None
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
            raise


def source_open_command(
    item: TodoItem, which=shutil.which
) -> list[str]:
    """Build a local editor command without interpreting task text in a shell."""
    for name in ("code", "codium", "gedit", "xdg-open"):
        editor = which(name)
        if not editor:
            continue
        if name in {"code", "codium"}:
            return [editor, "--goto", f"{item.source_path}:{item.line}"]
        if name == "gedit":
            return [editor, f"+{item.line}", str(item.source_path)]
        return [editor, str(item.source_path)]
    raise RuntimeError("No local editor or file opener is available.")


def open_source_item(item: TodoItem, popen=subprocess.Popen) -> None:
    """Launch the selected local source viewer without shell execution."""
    popen(source_open_command(item), start_new_session=True)


def _strip_markdown(text: str) -> str:
    """Return plain task copy while retaining its meaningful words."""
    text = re.sub(r"<!--.*?-->", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_due_date(text: str) -> date | None:
    match = DUE_RE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_todos(
    text: str, source_path: Path, project: str, today: date
) -> tuple[TodoItem, ...]:
    """Parse checkbox tasks with their current Markdown heading path."""
    del today  # Parsing is deterministic; ranking applies calendar context.
    headings: list[tuple[int, str]] = []
    items: list[TodoItem] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            level = len(heading_match.group(1))
            title = _strip_markdown(heading_match.group(2))
            headings = [entry for entry in headings if entry[0] < level]
            headings.append((level, title))
            continue

        task_match = TASK_RE.match(raw_line)
        if not task_match:
            continue
        raw_task = task_match.group(2)
        managed_match = MANAGED_ID_RE.search(raw_task)
        managed_id = managed_match.group(1) if managed_match else None
        display_text = _strip_markdown(raw_task)
        items.append(
            TodoItem(
                id=f"{source_path}:{line_number}",
                text=display_text,
                completed=task_match.group(1).lower() == "x",
                source_path=source_path,
                line=line_number,
                heading=" > ".join(title for _, title in headings),
                project=project,
                due_date=_parse_due_date(raw_task),
                managed_id=managed_id,
            )
        )
    return tuple(items)


def _ignored_directory(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_DIRS


def discover_todo_files(workspace_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """Return resolved TODO paths below project roots, within the depth limit."""
    discovered: set[Path] = set()
    for workspace_root in workspace_roots:
        root = Path(workspace_root)
        if not root.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(root):
            directory_path = Path(directory)
            relative = directory_path.relative_to(root)
            dirnames[:] = [name for name in dirnames if not _ignored_directory(name)]
            # The first path component is the project root; allow three below it.
            if len(relative.parts) > MAX_TODO_DEPTH + 1:
                dirnames[:] = []
                continue
            if "TODO.md" not in filenames or not relative.parts:
                continue
            candidate = directory_path / "TODO.md"
            try:
                discovered.add(candidate.resolve())
            except OSError:
                continue
    return tuple(sorted(discovered, key=str))


def _read_todo_file(path: Path) -> str | None:
    try:
        with path.open("rb") as todo_file:
            data = todo_file.read(MAX_TODO_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_TODO_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _project_for(path: Path, workspace_roots: tuple[Path, ...]) -> str:
    for workspace_root in workspace_roots:
        try:
            return path.relative_to(Path(workspace_root).resolve()).parts[0]
        except (ValueError, IndexError, OSError):
            continue
    return "Overall"


def _date_reason(due_date: date, today: date) -> tuple[int, str]:
    days_until_due = (due_date - today).days
    if days_until_due < 0:
        days_overdue = abs(days_until_due)
        suffix = "day" if days_overdue == 1 else "days"
        return 50, f"overdue by {days_overdue} {suffix}"
    if days_until_due == 0:
        return 28, "due today"
    if days_until_due == 1:
        return 20, "due tomorrow"
    return max(0, 14 - days_until_due), f"due in {days_until_due} days"


def rank_item(item: TodoItem, today: date) -> TodoItem:
    """Attach deterministic score, urgency, tags, and concise ranking reasons."""
    if item.completed:
        return replace(item, score=0, urgency="completed", why_now=(), waiting=False)

    score = 20
    reasons: list[tuple[int, int, str]] = [(0, 0, "open task needs attention")]
    context = f"{item.heading} {item.text}"
    reason_order = 1

    if item.due_date is not None:
        date_score, date_reason = _date_reason(item.due_date, today)
        score += date_score
        if date_score:
            reasons.append((date_score, reason_order, date_reason))
            reason_order += 1

    for weight, pattern, reason in SIGNALS:
        if re.search(pattern, context, re.I):
            score += weight
            reasons.append((weight, reason_order, reason))
            reason_order += 1

    if item.project == "Overall":
        score += 8
        reasons.append((8, reason_order, "captured in overall inbox"))
        reason_order += 1

    gate_match = GATE_RE.search(context)
    gate_date: date | None = None
    if gate_match:
        try:
            gate_date = date.fromisoformat(gate_match.group(1))
        except ValueError:
            gate_date = None

    waiting = bool(WAITING_RE.search(context)) or (
        gate_date is not None and gate_date > today
    )
    tags = item.tags
    if waiting and "waiting" not in tags:
        tags = (*tags, "waiting")
    if gate_date is not None and gate_date > today:
        reasons.append((100, reason_order, f"gated until {gate_date.isoformat()}"))
    elif waiting:
        reasons.append((100, reason_order, "explicitly waiting or on hold"))

    reasons.sort(key=lambda entry: (-entry[0], entry[1]))
    why_now = tuple(reason for _, _, reason in reasons[:4])
    urgency = "waiting" if waiting else "critical" if score >= 90 else "high" if score >= 65 else "normal"
    return replace(
        item,
        score=score,
        urgency=urgency,
        tags=tags,
        why_now=why_now,
        waiting=waiting,
    )


def _item_sort_key(item: TodoItem) -> tuple[object, ...]:
    return (
        item.completed,
        item.waiting if not item.completed else False,
        -item.score,
        item.due_date or date.max,
        item.project.lower(),
        str(item.source_path),
        item.line,
    )


def scan_todos(
    home_todo_path: Path, workspace_roots: tuple[Path, ...], today: date | None = None
) -> ScanResult:
    """Read the injected overall TODO plus bounded project TODO files."""
    current_day = today or date.today()
    home_path = Path(home_todo_path).resolve()
    paths: list[Path] = [home_path]
    paths.extend(path for path in discover_todo_files(workspace_roots) if path != home_path)

    warnings: list[str] = []
    items: list[TodoItem] = []
    scanned_files = 0
    for path in paths:
        contents = _read_todo_file(path)
        if contents is None:
            try:
                oversized = path.stat().st_size > MAX_TODO_BYTES
            except OSError:
                warnings.append(f"Skipped unreadable TODO file: {path}")
            else:
                warning = (
                    f"Skipped oversized TODO file: {path}"
                    if oversized
                    else f"Skipped unreadable TODO file: {path}"
                )
                warnings.append(warning)
            continue
        scanned_files += 1
        project = "Overall" if path == home_path else _project_for(path, workspace_roots)
        items.extend(
            rank_item(item, current_day)
            for item in parse_todos(contents, path, project, current_day)
        )

    return ScanResult(
        items=tuple(sorted(items, key=_item_sort_key)),
        warnings=tuple(warnings),
        scanned_files=scanned_files,
        generated_at=datetime.now(),
    )
