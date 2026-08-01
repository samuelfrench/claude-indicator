"""Local, bounded parsing and ranking for Markdown TODO files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

from PySide6.QtCore import QDate, QThread, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


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
FINISHED_MANAGED_KEY_RE = re.compile(r"managed:[0-9A-Za-z-]+$")
FINISHED_SOURCE_KEY_RE = re.compile(r"source:[0-9a-f]{64}$")
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
GATE_RE = re.compile(
    r"\b(?:on or after|no earlier than|only after|until)\s+"
    r"(20\d{2}-\d{2}-\d{2})\b",
    re.I,
)
WAITING_RE = re.compile(
    r"\bwaiting\b|wait for|\bhold\b|blocked(?:[\s-]+)by\b|"
    r"owner action|\bsam\s*:",
    re.I,
)


def _safe_read_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


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
    finished: bool = False


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


def todo_finished_key(item: TodoItem) -> str:
    """Return a stable, non-plaintext key for a locally finished task."""
    if item.managed_id is not None:
        key = f"managed:{item.managed_id}"
        if not FINISHED_MANAGED_KEY_RE.fullmatch(key):
            raise ValueError("Finished task has an invalid managed ID.")
        return key
    display_text = re.sub(r"\s+", " ", item.text).strip()
    identity = "\0".join((str(_absolute_path(item.source_path)), item.heading, display_text))
    return f"source:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _finished_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name, value in pairs:
        if name in payload:
            raise ValueError("Finished state contains duplicate JSON members.")
        payload[name] = value
    return payload


class FinishedStore:
    """Persist locally finished task keys without modifying their TODO sources."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> frozenset[str]:
        keys, _mode = self._read_current()
        return keys

    def finish(self, item: TodoItem) -> None:
        keys, mode = self._read_current()
        updated_keys = frozenset((*keys, todo_finished_key(item)))
        self._write_atomically(updated_keys, 0o600 if mode is None else mode)

    def restore(self, item: TodoItem) -> None:
        """Remove one locally finished task key without touching its TODO source."""
        keys, mode = self._read_current()
        key = todo_finished_key(item)
        if key not in keys:
            raise ValueError("Task is not finished.")
        self._write_atomically(keys - {key}, 0o600 if mode is None else mode)

    def _read_current(self) -> tuple[frozenset[str], int | None]:
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, _safe_read_flags())
        except FileNotFoundError:
            return frozenset(), None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ValueError("Finished state path must be a regular file.") from error
            raise ValueError("Finished state could not be read safely.") from error
        try:
            stat_result = os.fstat(descriptor)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValueError("Finished state path must be a regular file.")
            data = os.read(descriptor, stat_result.st_size + 1)
        except OSError as error:
            raise ValueError("Finished state could not be read safely.") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_finished_json_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Finished state is malformed.") from error
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "finished"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or not isinstance(payload["finished"], list)
            or not all(isinstance(key, str) for key in payload["finished"])
        ):
            raise ValueError("Finished state has an unsupported schema.")
        finished_keys = payload["finished"]
        if (
            finished_keys != sorted(set(finished_keys))
            or not all(
                FINISHED_MANAGED_KEY_RE.fullmatch(key)
                or FINISHED_SOURCE_KEY_RE.fullmatch(key)
                for key in finished_keys
            )
        ):
            raise ValueError("Finished state has noncanonical keys.")
        return frozenset(finished_keys), stat_result.st_mode & 0o7777

    def _write_atomically(self, keys: frozenset[str], mode: int) -> None:
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": 1, "finished": sorted(keys)},
                separators=(",", ":"),
            )
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(payload)
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
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, _safe_read_flags())
        except FileNotFoundError:
            return "# TODO\n", 0o644
        try:
            stat_result = os.fstat(descriptor)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValueError("Indicator Inbox path must be a regular file.")
            with os.fdopen(
                descriptor,
                mode="r",
                encoding="utf-8",
                newline="",
            ) as todo_file:
                descriptor = None
                return todo_file.read(), stat_result.st_mode & 0o7777
        finally:
            if descriptor is not None:
                os.close(descriptor)

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
                newline="",
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
            )
        )
    return tuple(items)


def _ignored_directory(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_DIRS


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _discover_todo_files(
    workspace_roots: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """Discover confined TODO candidates and report paths that were skipped."""
    discovered: set[Path] = set()
    warnings: list[str] = []
    seen_roots: set[Path] = set()
    for workspace_root in workspace_roots:
        configured_root = _absolute_path(Path(workspace_root))
        try:
            root = configured_root.resolve(strict=True)
        except OSError:
            warnings.append(f"Skipped unavailable workspace root: {configured_root}")
            continue
        if (
            root in seen_roots
            or not root.is_dir()
            or not os.access(root, os.R_OK | os.X_OK)
        ):
            if root not in seen_roots:
                warnings.append(f"Skipped unavailable workspace root: {configured_root}")
            continue
        seen_roots.add(root)

        def warn_walk_error(error: OSError) -> None:
            path = _absolute_path(Path(error.filename or root))
            warnings.append(f"Skipped unreadable workspace path: {path}")

        for directory, dirnames, filenames in os.walk(
            root,
            topdown=True,
            onerror=warn_walk_error,
            followlinks=False,
        ):
            directory_path = Path(directory)
            relative = directory_path.relative_to(root)
            allowed_directories: list[str] = []
            for name in sorted(dirnames):
                if _ignored_directory(name):
                    continue
                child = directory_path / name
                if child.is_symlink():
                    continue
                allowed_directories.append(name)
            dirnames[:] = allowed_directories

            # Each root contains project directories. At project + three nested
            # directories, process this directory but do not enter a fourth.
            if len(relative.parts) >= MAX_TODO_DEPTH + 1:
                dirnames[:] = []
            if "TODO.md" not in filenames or not relative.parts:
                continue
            candidate = directory_path / "TODO.md"
            if candidate.is_symlink():
                warnings.append(f"Skipped symlink TODO file: {candidate}")
                continue
            try:
                resolved_candidate = candidate.resolve(strict=True)
            except OSError:
                warnings.append(f"Skipped unreadable TODO file: {candidate}")
                continue
            if not resolved_candidate.is_relative_to(root):
                warnings.append(f"Skipped escaped TODO file: {candidate}")
                continue
            discovered.add(resolved_candidate)
    return tuple(sorted(discovered, key=str)), tuple(warnings)


def discover_todo_files(workspace_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """Return confined TODO paths below project roots, within the depth limit."""
    paths, _warnings = _discover_todo_files(workspace_roots)
    return paths


def _read_todo_file(path: Path) -> tuple[str | None, str | None]:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _safe_read_flags())
    except OSError as error:
        warning_kind = "symlink" if error.errno == errno.ELOOP else "unreadable"
        return None, f"Skipped {warning_kind} TODO file: {path}"
    try:
        stat_result = os.fstat(descriptor)
        if not stat.S_ISREG(stat_result.st_mode):
            return None, f"Skipped special TODO file: {path}"
        if stat_result.st_size > MAX_TODO_BYTES:
            return None, f"Skipped oversized TODO file: {path}"
        chunks: list[bytes] = []
        remaining = MAX_TODO_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError:
        return None, f"Skipped unreadable TODO file: {path}"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) > MAX_TODO_BYTES:
        return None, f"Skipped oversized TODO file: {path}"
    return data.decode("utf-8", errors="replace"), None


def _managed_ids_by_line(contents: str) -> dict[int, str]:
    """Return managed IDs only for checkboxes inside one valid marker pair."""
    try:
        start, end = InboxStore._managed_bounds(contents)
    except ValueError:
        return {}
    if start is None or end is None:
        return {}

    managed_ids: dict[int, str] = {}
    offset = 0
    for line_number, raw_line in enumerate(contents.splitlines(keepends=True), start=1):
        line_start = offset
        offset += len(raw_line)
        if line_start < start or line_start >= end:
            continue
        task_match = TASK_RE.match(raw_line.rstrip("\r\n"))
        if not task_match:
            continue
        managed_match = MANAGED_ID_RE.search(task_match.group(2))
        if managed_match:
            managed_ids[line_number] = managed_match.group(1)
    return managed_ids


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
    home_path = _absolute_path(Path(home_todo_path))
    discovered_paths, discovery_warnings = _discover_todo_files(workspace_roots)
    paths: list[Path] = [home_path]
    paths.extend(path for path in discovered_paths if path != home_path)

    warnings = list(discovery_warnings)
    items: list[TodoItem] = []
    scanned_files = 0
    for path in paths:
        contents, warning = _read_todo_file(path)
        if contents is None:
            if warning is not None:
                warnings.append(warning)
            continue
        scanned_files += 1
        project = "Overall" if path == home_path else _project_for(path, workspace_roots)
        parsed_items = parse_todos(contents, path, project, current_day)
        if path == home_path:
            managed_ids = _managed_ids_by_line(contents)
            parsed_items = tuple(
                replace(item, managed_id=managed_ids.get(item.line))
                for item in parsed_items
            )
        items.extend(rank_item(item, current_day) for item in parsed_items)

    return ScanResult(
        items=tuple(sorted(items, key=_item_sort_key)),
        warnings=tuple(warnings),
        scanned_files=scanned_files,
        generated_at=datetime.now(),
    )


SMART_TODO_STYLESHEET = """
QDialog#smartTodoDialog {
    background: #14141E;
    color: #B4B4C8;
}
QLabel {
    color: #B4B4C8;
    font-size: 12px;
}
QLabel#dialogTitle {
    color: #D4A574;
    font-size: 17px;
    font-weight: 600;
}
QLabel#utilityLabel, QLabel#taskMeta, QLabel#whyEyebrow, QLabel#summaryLabel {
    color: #B4B4C8;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#warningLabel {
    background: #20202D;
    border-left: 3px solid #F87171;
    color: #F87171;
    padding: 8px 10px;
}
QLabel#statusLabel {
    color: #B4B4C8;
    font-size: 10px;
}
QLineEdit, QDateEdit, QComboBox {
    background: #20202D;
    border: 1px solid #B4B4C8;
    border-radius: 5px;
    color: #B4B4C8;
    font-size: 12px;
    min-height: 30px;
    padding: 0 8px;
    selection-background-color: #8B5CF6;
}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QPushButton:focus,
QWidget#taskRow:focus {
    border: 2px solid #D4A574;
}
QComboBox QAbstractItemView {
    background: #20202D;
    color: #B4B4C8;
    selection-background-color: #8B5CF6;
}
QCheckBox {
    border: 2px solid #14141E;
    border-radius: 3px;
    color: #B4B4C8;
    font-size: 10px;
    padding: 2px;
    spacing: 6px;
}
QCheckBox:focus {
    border-color: #D4A574;
}
QCheckBox::indicator {
    border: 1px solid #B4B4C8;
    height: 14px;
    width: 14px;
}
QCheckBox::indicator:checked {
    background: #8B5CF6;
}
QPushButton {
    background: #20202D;
    border: 1px solid #8B5CF6;
    border-radius: 5px;
    color: #B4B4C8;
    font-size: 10px;
    font-weight: 600;
    min-height: 30px;
    padding: 0 10px;
}
QPushButton:hover {
    background: #8B5CF6;
}
QPushButton:disabled {
    border-color: #20202D;
    color: #B4B4C8;
}
QPushButton#addButton {
    background: #D4A574;
    border-color: #D4A574;
    color: #14141E;
}
QPushButton#completeButton {
    border-color: #D4A574;
}
QScrollArea {
    background: #14141E;
    border: 1px solid #20202D;
    border-radius: 6px;
}
QScrollArea > QWidget > QWidget {
    background: #14141E;
}
QWidget#taskRow {
    background: #20202D;
    border: 1px solid #20202D;
    border-left: 3px solid #B4B4C8;
    border-radius: 5px;
}
QWidget#taskRow[urgency="critical"] {
    border-left-color: #F87171;
}
QWidget#taskRow[urgency="high"] {
    border-left-color: #D4A574;
}
QWidget#taskRow[urgency="waiting"] {
    border-left-color: #B4B4C8;
}
QWidget#taskRow[selected="true"] {
    background: #8B5CF6;
    border-color: #D4A574;
}
QWidget#taskRow[selected="true"] QLabel {
    color: #14141E;
}
QWidget#taskRow[selected="true"] QPushButton {
    background: #14141E;
    color: #B4B4C8;
}
QLabel#taskText {
    color: #B4B4C8;
    font-size: 12px;
    font-weight: 600;
}
QFrame#whyRail {
    background: #20202D;
    border: 1px solid #20202D;
    border-left: 4px solid #D4A574;
    border-radius: 6px;
}
QLabel#whyEyebrow {
    color: #D4A574;
}
QLabel#whyTitle {
    color: #B4B4C8;
    font-size: 17px;
    font-weight: 600;
}
QLabel#whyReasons {
    color: #B4B4C8;
    font-size: 12px;
}
"""


class TodoScanWorker(QThread):
    """Run bounded local TODO discovery without blocking the UI thread."""

    result = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        home_todo_path: Path,
        workspace_roots: tuple[Path, ...],
        today: date,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.home_todo_path = Path(home_todo_path)
        self.workspace_roots = tuple(Path(root) for root in workspace_roots)
        self.today = today

    def run(self) -> None:
        try:
            scan_result = scan_todos(
                self.home_todo_path,
                self.workspace_roots,
                today=self.today,
            )
        except Exception as error:  # Keep an unexpected scan failure inside the dialog.
            self.failed.emit(str(error) or error.__class__.__name__)
            return
        self.result.emit(scan_result)


class ElidedLabel(QLabel):
    """Render one compact line while preserving the complete accessible copy."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFullText(text)

    def setFullText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setAccessibleDescription(f"Full text: {text}")
        self._update_elision()

    def _update_elision(self) -> None:
        available_width = max(1, self.contentsRect().width())
        super().setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_elision()


class TodoTaskRow(QWidget):
    """Compact task summary with safe completion and source actions."""

    complete_requested = Signal(str)
    dismiss_requested = Signal(object)
    open_requested = Signal(object)
    selected = Signal(object)

    def __init__(self, item: TodoItem, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("taskRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("urgency", item.urgency)
        self.setProperty("selected", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Task: {item.text}; {item.urgency} urgency")
        self.setAccessibleDescription(
            f"{item.urgency.capitalize()} urgency task from {item.project}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        copy_layout = QVBoxLayout()
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(3)
        self.text_label = ElidedLabel(item.text)
        self.text_label.setObjectName("taskText")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        due_copy = item.due_date.isoformat() if item.due_date else "NO DUE DATE"
        self.meta_label = QLabel(
            f"{item.urgency.upper()} URGENCY  ·  SCORE {item.score}  ·  "
            f"{item.project.upper()}  ·  {due_copy}"
        )
        self.meta_label.setObjectName("taskMeta")
        self.meta_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.meta_label.setAccessibleName(
            f"{item.urgency} urgency, score {item.score}, "
            f"project {item.project}, {due_copy.lower()}"
        )
        self.meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        copy_layout.addWidget(self.text_label)
        copy_layout.addWidget(self.meta_label)
        layout.addLayout(copy_layout, 1)

        self.open_button = QPushButton("Open source")
        self.open_button.setAccessibleName(f"Open source for {item.text}")
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self.item))
        layout.addWidget(self.open_button)

        self.complete_button: QPushButton | None = None
        if item.managed_id is not None and not item.completed and not item.finished:
            self.complete_button = QPushButton("Complete")
            self.complete_button.setObjectName("completeButton")
            self.complete_button.setAccessibleName(f"Complete {item.text}")
            self.complete_button.clicked.connect(
                lambda: self.complete_requested.emit(item.managed_id or "")
            )
            layout.addWidget(self.complete_button)

        self.dismiss_button: QPushButton | None = None
        if not item.completed and not item.finished:
            self.dismiss_button = QPushButton("Dismiss")
            self.dismiss_button.setObjectName("dismissButton")
            self.dismiss_button.setAccessibleName(f"Dismiss {item.text}")
            self.dismiss_button.clicked.connect(
                lambda: self.dismiss_requested.emit(self.item)
            )
            layout.addWidget(self.dismiss_button)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        styled_widgets = [
            self,
            self.text_label,
            self.meta_label,
            self.open_button,
        ]
        if self.complete_button is not None:
            styled_widgets.append(self.complete_button)
        if self.dismiss_button is not None:
            styled_widgets.append(self.dismiss_button)
        for widget in styled_widgets:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.item)
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_requested.emit(self.item)
            event.accept()
            return
        super().keyPressEvent(event)


class SmartTodoDialog(QDialog):
    """Modeless local command center for capturing and ranking TODO items."""

    summary_changed = Signal(int, int)

    def __init__(
        self,
        *,
        home_todo_path: Path = Path.home() / "TODO.md",
        workspace_roots: tuple[Path, ...] = (
            Path.home() / "claude-workspace",
            Path.home() / "codex_workspace",
        ),
        today_provider: Callable[[], date] = date.today,
        finished_store_path: Path = Path.home() / ".claude" / "smart_todos_finished.json",
        parent: QWidget | None = None,
    ):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.home_todo_path = Path(home_todo_path)
        self.workspace_roots = tuple(Path(root) for root in workspace_roots)
        self.today_provider = today_provider
        self.finished_store_path = Path(finished_store_path)
        self._all_items: tuple[TodoItem, ...] = ()
        self._worker: TodoScanWorker | None = None
        self._worker_finished_slots: dict[
            TodoScanWorker, Callable[[], None]
        ] = {}
        self._refresh_pending = False
        self._shutting_down = False
        self._scan_today = self.today_provider()
        self._selected_item_id: str | None = None
        self.task_rows: list[TodoTaskRow] = []

        self.setObjectName("smartTodoDialog")
        self.setWindowTitle("Smart TODOs")
        self.setMinimumSize(760, 620)
        self.resize(860, 680)
        self.setStyleSheet(SMART_TODO_STYLESHEET)
        self._build_ui()
        self._set_tab_order()

    @property
    def worker(self) -> TodoScanWorker | None:
        return self._worker

    @property
    def refresh_pending(self) -> bool:
        return self._refresh_pending

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        heading_layout = QVBoxLayout()
        heading_layout.setSpacing(2)
        title = QLabel("Smart TODO command center")
        title.setObjectName("dialogTitle")
        title.setAccessibleName("Smart TODO command center")
        subtitle = QLabel("Capture work. Decide what needs attention now.")
        heading_layout.addWidget(title)
        heading_layout.addWidget(subtitle)
        header.addLayout(heading_layout, 1)
        self.summary_label = QLabel("0 focus  ·  0 overdue  ·  0 urgent  ·  0 waiting  ·  0 open")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setAccessibleName("TODO summary")
        header.addWidget(self.summary_label, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        capture_label = QLabel("CAPTURE")
        capture_label.setObjectName("utilityLabel")
        root.addWidget(capture_label)
        capture = QHBoxLayout()
        capture.setSpacing(7)
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("What needs attention?")
        self.task_input.setAccessibleName("New task")
        self.task_input.returnPressed.connect(self._add_task)
        capture.addWidget(self.task_input, 1)
        self.due_date_edit = QDateEdit()
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.due_date_edit.setDate(QDate(self._scan_today.year, self._scan_today.month, self._scan_today.day))
        self.due_date_edit.setAccessibleName("Task due date")
        self.no_due_checkbox = QCheckBox("No due date")
        self.no_due_checkbox.setChecked(True)
        self.no_due_checkbox.setAccessibleName("No due date")
        self.no_due_checkbox.toggled.connect(
            lambda checked: self.due_date_edit.setDisabled(checked)
        )
        self.due_date_edit.setDisabled(True)
        capture.addWidget(self.due_date_edit)
        capture.addWidget(self.no_due_checkbox)
        self.add_button = QPushButton("Add task")
        self.add_button.setObjectName("addButton")
        self.add_button.setAccessibleName("Add task")
        self.add_button.clicked.connect(self._add_task)
        capture.addWidget(self.add_button)
        root.addLayout(capture)

        filter_label = QLabel("DECIDE WHAT NEEDS ATTENTION NOW")
        filter_label.setObjectName("utilityLabel")
        root.addWidget(filter_label)
        filters = QHBoxLayout()
        filters.setSpacing(7)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search task, project, heading, or reason")
        self.search_edit.setAccessibleName("Search tasks")
        self.search_edit.textChanged.connect(self._render_items)
        filters.addWidget(self.search_edit, 1)
        self.project_combo = QComboBox()
        self.project_combo.addItem("All projects")
        self.project_combo.setAccessibleName("Project filter")
        self.project_combo.currentTextChanged.connect(self._render_items)
        filters.addWidget(self.project_combo)
        self.view_combo = QComboBox()
        self.view_combo.addItems(("Focus", "All open", "Waiting", "Completed inbox", "Finished"))
        self.view_combo.setAccessibleName("Task view")
        self.view_combo.currentTextChanged.connect(self._render_items)
        filters.addWidget(self.view_combo)
        self.reset_filters_button = QPushButton("Reset")
        self.reset_filters_button.setAccessibleName("Reset filters")
        self.reset_filters_button.clicked.connect(self._reset_filters)
        filters.addWidget(self.reset_filters_button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setAccessibleName("Refresh TODO files")
        self.refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.refresh_button)
        root.addLayout(filters)

        content = QHBoxLayout()
        content.setSpacing(10)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAccessibleName("Ranked tasks")
        self.task_list_widget = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_list_widget)
        self.task_list_layout.setContentsMargins(7, 7, 7, 7)
        self.task_list_layout.setSpacing(6)
        self.loading_label = QLabel("Loading ranked TODOs…")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setMinimumHeight(56)
        self.loading_label.hide()
        self.empty_label = QLabel("No TODO items found. Add one above.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(56)
        self.empty_label.show()
        self.render_limit_label = QLabel()
        self.render_limit_label.setObjectName("utilityLabel")
        self.render_limit_label.hide()
        self.task_list_layout.addWidget(self.loading_label)
        self.task_list_layout.addWidget(self.empty_label)
        self.task_list_layout.addWidget(self.render_limit_label)
        self.task_list_layout.addStretch(1)
        self.scroll_area.setWidget(self.task_list_widget)
        content.addWidget(self.scroll_area, 1)

        self.why_rail = QFrame()
        self.why_rail.setObjectName("whyRail")
        self.why_rail.setMinimumWidth(230)
        self.why_rail.setMaximumWidth(280)
        self.why_rail.setAccessibleName("Why now details")
        why_layout = QVBoxLayout(self.why_rail)
        why_layout.setContentsMargins(14, 14, 14, 14)
        why_layout.setSpacing(9)
        why_eyebrow = QLabel("WHY NOW")
        why_eyebrow.setObjectName("whyEyebrow")
        self.why_title_label = ElidedLabel("Select a task")
        self.why_title_label.setObjectName("whyTitle")
        self.why_meta_label = QLabel("Score and source context appear here.")
        self.why_meta_label.setObjectName("taskMeta")
        self.why_meta_label.setWordWrap(True)
        self.why_reasons_label = QLabel(
            "The strongest due-date, priority, customer, billing, and verification signals are explained here."
        )
        self.why_reasons_label.setObjectName("whyReasons")
        self.why_reasons_label.setWordWrap(True)
        self.why_reasons_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        why_layout.addWidget(why_eyebrow)
        why_layout.addWidget(self.why_title_label)
        why_layout.addWidget(self.why_meta_label)
        why_layout.addWidget(self.why_reasons_label, 1)
        content.addWidget(self.why_rail)
        root.addLayout(content, 1)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setAccessibleName("Scan warnings")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        root.addWidget(self.warning_label)
        self.status_label = QLabel("Ready to scan local TODO files.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAccessibleName("TODO status")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _set_tab_order(self) -> None:
        self.setTabOrder(self.task_input, self.due_date_edit)
        self.setTabOrder(self.due_date_edit, self.no_due_checkbox)
        self.setTabOrder(self.no_due_checkbox, self.add_button)
        self.setTabOrder(self.add_button, self.search_edit)
        self.setTabOrder(self.search_edit, self.project_combo)
        self.setTabOrder(self.project_combo, self.view_combo)
        self.setTabOrder(self.view_combo, self.reset_filters_button)
        self.setTabOrder(self.reset_filters_button, self.refresh_button)

    def show_and_refresh(self) -> None:
        self.show()
        if QApplication.platformName() != "offscreen":
            self.raise_()
            self.activateWindow()
        self.refresh()

    def refresh(self) -> None:
        if self._shutting_down:
            return
        if self._worker is not None:
            self._refresh_pending = True
            return
        try:
            self._scan_today = self.today_provider()
        except Exception as error:
            self.status_label.setText(str(error) or error.__class__.__name__)
            return
        self.refresh_button.setDisabled(True)
        self.loading_label.show()
        self.empty_label.hide()
        self.render_limit_label.hide()
        self.status_label.setText("Scanning local TODO files…")
        worker = TodoScanWorker(
            home_todo_path=self.home_todo_path,
            workspace_roots=self.workspace_roots,
            today=self._scan_today,
            parent=self,
        )
        self._worker = worker
        worker.result.connect(self._on_scan_result)
        worker.failed.connect(self._on_scan_failed)
        finished_slot = lambda worker=worker: self._on_worker_finished(worker)
        self._worker_finished_slots[worker] = finished_slot
        worker.finished.connect(finished_slot)
        worker.start()

    def _on_scan_result(self, scan_result: ScanResult) -> None:
        if self._shutting_down:
            return
        warnings = list(scan_result.warnings)
        try:
            finished_keys = FinishedStore(self.finished_store_path).read()
        except Exception as error:
            finished_keys = frozenset()
            warnings.append(str(error) or error.__class__.__name__)
        self._all_items = tuple(
            replace(item, finished=todo_finished_key(item) in finished_keys)
            for item in scan_result.items
        )
        self._update_summary()
        self._rebuild_project_filter()
        self.warning_label.setText("\n".join(warnings))
        self.warning_label.setVisible(bool(warnings))
        self.status_label.setText(
            f"Scanned {scan_result.scanned_files} TODO files · {len(scan_result.items)} tasks."
        )
        self._render_items()

    def _on_scan_failed(self, message: str) -> None:
        if self._shutting_down:
            return
        self.loading_label.hide()
        self.status_label.setText(message)
        if not self._all_items:
            self.empty_label.setText("TODO scan failed. Refresh to try again.")
            self.empty_label.show()

    def _on_worker_finished(self, worker: TodoScanWorker) -> None:
        self._worker_finished_slots.pop(worker, None)
        worker.deleteLater()
        if worker is not self._worker:
            return
        self._worker = None
        self.refresh_button.setEnabled(not self._shutting_down)
        if self._refresh_pending and not self._shutting_down:
            self._refresh_pending = False
            self.refresh()

    def _update_summary(self) -> None:
        open_items = [
            item for item in self._all_items if not item.completed and not item.finished
        ]
        focus_count = sum(not item.waiting for item in open_items)
        overdue_count = sum(
            item.due_date is not None and item.due_date < self._scan_today
            for item in open_items
        )
        urgent_count = sum(
            item.urgency in {"critical", "high"} and not item.waiting
            for item in open_items
        )
        waiting_count = sum(item.waiting for item in open_items)
        self.summary_label.setText(
            f"{focus_count} focus  ·  {overdue_count} overdue  ·  "
            f"{urgent_count} urgent  ·  {waiting_count} waiting  ·  {len(open_items)} open"
        )
        self.summary_changed.emit(focus_count, overdue_count)

    def _rebuild_project_filter(self) -> None:
        selected_project = self.project_combo.currentText()
        projects = sorted({item.project for item in self._all_items}, key=str.casefold)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("All projects")
        self.project_combo.addItems(projects)
        if selected_project in projects:
            self.project_combo.setCurrentText(selected_project)
        self.project_combo.blockSignals(False)

    def _filtered_items(self) -> tuple[TodoItem, ...]:
        view = self.view_combo.currentText()
        project = self.project_combo.currentText()
        query = self.search_edit.text().strip().casefold()
        filtered: list[TodoItem] = []
        for item in self._all_items:
            if view == "Focus" and (item.completed or item.finished or item.waiting):
                continue
            if view == "All open" and (item.completed or item.finished):
                continue
            if view == "Waiting" and (item.completed or item.finished or not item.waiting):
                continue
            if view == "Completed inbox" and (
                not item.completed or item.managed_id is None
            ):
                continue
            if view == "Finished" and (not item.finished or item.completed):
                continue
            if project != "All projects" and item.project != project:
                continue
            if query:
                search_values = (
                    item.text,
                    item.project,
                    item.heading,
                    *item.tags,
                    *item.why_now,
                )
                if query not in " ".join(search_values).casefold():
                    continue
            filtered.append(item)
        return tuple(filtered)

    def _clear_task_rows(self) -> None:
        for row in self.task_rows:
            self.task_list_layout.removeWidget(row)
            row.deleteLater()
        self.task_rows = []

    def _render_items(self, *_args) -> None:
        self.loading_label.hide()
        self._clear_task_rows()
        filtered = self._filtered_items()
        visible_items = filtered[:MAX_VISIBLE_ITEMS]
        for item in visible_items:
            row = TodoTaskRow(item, self.task_list_widget)
            row.selected.connect(self._select_item)
            row.complete_requested.connect(self._complete_task)
            row.dismiss_requested.connect(self._dismiss_task)
            row.open_requested.connect(self._open_item)
            self.task_list_layout.insertWidget(self.task_list_layout.count() - 1, row)
            self.task_rows.append(row)

        if not filtered:
            message = (
                "No TODO items found. Add one above."
                if not self._all_items
                else "No tasks match this view. Reset filters or choose another view."
            )
            self.empty_label.setText(message)
            self.empty_label.show()
        else:
            self.empty_label.hide()

        if len(filtered) > MAX_VISIBLE_ITEMS:
            self.render_limit_label.setText(
                f"Showing first {MAX_VISIBLE_ITEMS} of {len(filtered)} matching tasks."
            )
            self.render_limit_label.show()
        else:
            self.render_limit_label.hide()

        selected = next(
            (item for item in visible_items if item.id == self._selected_item_id),
            visible_items[0] if visible_items else None,
        )
        if selected is None:
            self._selected_item_id = None
            self.why_title_label.setFullText("No task selected")
            self.why_meta_label.setText("Choose a populated view to inspect ranking context.")
            self.why_reasons_label.setText(
                "Why-now reasons appear here when a task is selected."
            )
        else:
            self._select_item(selected)

    def _select_item(self, item: TodoItem) -> None:
        self._selected_item_id = item.id
        for row in self.task_rows:
            row.set_selected(row.item.id == item.id)
        self.why_title_label.setFullText(item.text)
        due_copy = item.due_date.isoformat() if item.due_date else "No due date"
        source_copy = (
            f"{item.urgency.capitalize()} urgency · {item.project} · "
            f"score {item.score} · {due_copy}"
        )
        if item.heading:
            source_copy += f"\n{item.heading}"
        self.why_meta_label.setText(source_copy)
        self.why_meta_label.setAccessibleName(
            f"{item.urgency} urgency task details"
        )
        reasons = (
            ("Finished in the command center. Source TODO was not changed.",)
            if item.finished
            else item.why_now
            or ("Completed inbox item." if item.completed else "Open task needs attention.",)
        )
        self.why_reasons_label.setText("\n\n".join(f"— {reason}" for reason in reasons))

    def _reset_filters(self) -> None:
        self.search_edit.blockSignals(True)
        self.project_combo.blockSignals(True)
        self.view_combo.blockSignals(True)
        self.search_edit.clear()
        self.project_combo.setCurrentText("All projects")
        self.view_combo.setCurrentText("Focus")
        self.search_edit.blockSignals(False)
        self.project_combo.blockSignals(False)
        self.view_combo.blockSignals(False)
        self._render_items()

    def _add_task(self) -> None:
        due_date = None
        if not self.no_due_checkbox.isChecked():
            due_date = self.due_date_edit.date().toPython()
        try:
            InboxStore(self.home_todo_path).add(self.task_input.text(), due_date)
        except Exception as error:
            self.status_label.setText(str(error) or error.__class__.__name__)
            return
        self.task_input.clear()
        self.status_label.setText("Task added. Refreshing local TODO files…")
        self.refresh()

    def _complete_task(self, managed_id: str) -> None:
        item = next(
            (
                candidate
                for candidate in self._all_items
                if candidate.managed_id == managed_id and not candidate.completed
            ),
            None,
        )
        if item is None:
            self.status_label.setText("Only open Indicator Inbox tasks can be completed here.")
            return
        try:
            InboxStore(self.home_todo_path).complete(managed_id)
        except Exception as error:
            self.status_label.setText(str(error) or error.__class__.__name__)
            return
        self.status_label.setText("Task completed. Refreshing local TODO files…")
        self.refresh()

    def _dismiss_task(self, item: TodoItem) -> None:
        current_item = next(
            (candidate for candidate in self._all_items if candidate.id == item.id),
            None,
        )
        if current_item is None or current_item.completed or current_item.finished:
            self.status_label.setText("Only active tasks can be dismissed here.")
            return
        try:
            finished_key = todo_finished_key(current_item)
            FinishedStore(self.finished_store_path).finish(current_item)
        except Exception as error:
            self.status_label.setText(str(error) or error.__class__.__name__)
            return
        self._all_items = tuple(
            replace(candidate, finished=True)
            if todo_finished_key(candidate) == finished_key
            else candidate
            for candidate in self._all_items
        )
        self._update_summary()
        self.status_label.setText("Task finished in command center. Source TODO unchanged.")
        self._render_items()

    def _open_item(self, item: TodoItem) -> None:
        try:
            open_source_item(item)
        except Exception as error:
            self.status_label.setText(str(error) or error.__class__.__name__)

    def shutdown(self) -> None:
        self._shutting_down = True
        self._refresh_pending = False
        worker = self._worker
        if worker is None:
            return
        for signal, slot in (
            (worker.result, self._on_scan_result),
            (worker.failed, self._on_scan_failed),
        ):
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass
        finished_slot = self._worker_finished_slots.pop(worker, None)
        if finished_slot is not None:
            try:
                worker.finished.disconnect(finished_slot)
            except RuntimeError:
                pass
        if worker.isRunning():
            worker.wait()
        worker.deleteLater()
        self._worker = None
