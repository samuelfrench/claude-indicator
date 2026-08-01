"""Strict local persistence for Smart TODO workflow choices and scan history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import errno
import json
import os
from pathlib import Path
import re
import stat
import tempfile


MANAGED_KEY_RE = re.compile(r"managed:[0-9A-Za-z-]+$")
SOURCE_KEY_RE = re.compile(r"source:[0-9a-f]{64}$")
LOCATION_KEY_RE = re.compile(r"location:[0-9a-f]{64}$")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}$")


def _safe_read_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


@dataclass(frozen=True)
class TaskObservation:
    location: str
    content: str
    source_modified_on: date


@dataclass(frozen=True)
class ObservedTask:
    location: str
    content: str
    unchanged_since: date
    change: str


@dataclass(frozen=True, order=True)
class SnoozeRecord:
    key: str
    until: date


@dataclass(frozen=True, order=True)
class ObservedRecord:
    location: str
    content: str
    unchanged_since: date


@dataclass(frozen=True)
class WorkflowState:
    pinned_today: frozenset[str]
    snoozed: tuple[SnoozeRecord, ...]
    observed: tuple[ObservedRecord, ...]


EMPTY_STATE = WorkflowState(frozenset(), (), ())


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Workflow state contains duplicate JSON members.")
        result[name] = value
    return result


def _parse_date(value: object) -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError("Workflow state has invalid dates.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Workflow state has invalid dates.") from error


def _is_content_key(key: object) -> bool:
    return isinstance(key, str) and bool(
        MANAGED_KEY_RE.fullmatch(key) or SOURCE_KEY_RE.fullmatch(key)
    )


def _is_location_key(key: object) -> bool:
    return isinstance(key, str) and bool(
        MANAGED_KEY_RE.fullmatch(key) or LOCATION_KEY_RE.fullmatch(key)
    )


def _parse_snooze(value: object) -> SnoozeRecord:
    if not isinstance(value, dict) or set(value) != {"key", "until"}:
        raise ValueError("Workflow state has an unsupported schema.")
    key = value["key"]
    if not _is_content_key(key):
        raise ValueError("Workflow state has invalid keys.")
    return SnoozeRecord(key, _parse_date(value["until"]))


def _parse_observed(value: object) -> ObservedRecord:
    if not isinstance(value, dict) or set(value) != {
        "location", "content", "unchanged_since"
    }:
        raise ValueError("Workflow state has an unsupported schema.")
    location = value["location"]
    content = value["content"]
    if not _is_location_key(location) or not _is_content_key(content):
        raise ValueError("Workflow state has invalid keys.")
    if MANAGED_KEY_RE.fullmatch(str(content)) and location != content:
        raise ValueError("Workflow state has invalid keys.")
    return ObservedRecord(location, content, _parse_date(value["unchanged_since"]))


def _state_from_payload(payload: object) -> WorkflowState:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "pinned_today", "snoozed", "observed"}
        or type(payload["version"]) is not int
        or payload["version"] != 1
        or not isinstance(payload["pinned_today"], list)
        or not isinstance(payload["snoozed"], list)
        or not isinstance(payload["observed"], list)
    ):
        raise ValueError("Workflow state has an unsupported schema.")

    pins = payload["pinned_today"]
    if not all(_is_content_key(key) for key in pins) or pins != sorted(set(pins)):
        raise ValueError("Workflow state has noncanonical keys.")
    snoozes = tuple(_parse_snooze(value) for value in payload["snoozed"])
    observed = tuple(_parse_observed(value) for value in payload["observed"])
    if snoozes != tuple(sorted(set(snoozes))) or observed != tuple(sorted(set(observed))):
        raise ValueError("Workflow state has noncanonical records.")
    if len({record.key for record in snoozes}) != len(snoozes):
        raise ValueError("Workflow state has duplicate snooze keys.")
    if len({record.location for record in observed}) != len(observed):
        raise ValueError("Workflow state has duplicate observed locations.")
    return WorkflowState(frozenset(pins), snoozes, observed)


class WorkflowStore:
    """Atomically persist local workflow state without task text."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> WorkflowState:
        return self._read_current()[0]

    def pin(
        self,
        key: str,
        *,
        legacy_key: str | None = None,
        replacement_keys: tuple[str, ...] = (),
    ) -> None:
        self._require_content_key(key)
        self._validate_legacy_expansion(legacy_key, replacement_keys)
        self._mutate(lambda state: self._pin(
            self._expand_legacy_key(state, legacy_key, replacement_keys), key
        ))

    def unpin(
        self,
        key: str,
        *,
        legacy_key: str | None = None,
        replacement_keys: tuple[str, ...] = (),
    ) -> None:
        self._require_content_key(key)
        self._validate_legacy_expansion(legacy_key, replacement_keys)
        self._mutate(lambda state: self._unpin(
            self._expand_legacy_key(state, legacy_key, replacement_keys), key
        ))

    def snooze(
        self,
        key: str,
        until: date,
        *,
        legacy_key: str | None = None,
        replacement_keys: tuple[str, ...] = (),
    ) -> None:
        self._require_content_key(key)
        if not isinstance(until, date) or until <= date.today():
            raise ValueError("Workflow snoozes must be for a future date.")
        self._validate_legacy_expansion(legacy_key, replacement_keys)
        self._mutate(lambda state: self._snooze(
            self._expand_legacy_key(state, legacy_key, replacement_keys), key, until
        ))

    def wake(
        self,
        key: str,
        *,
        legacy_key: str | None = None,
        replacement_keys: tuple[str, ...] = (),
    ) -> None:
        self._require_content_key(key)
        self._validate_legacy_expansion(legacy_key, replacement_keys)
        self._mutate(lambda state: self._wake(
            self._expand_legacy_key(state, legacy_key, replacement_keys), key
        ))

    @staticmethod
    def _pin(state: WorkflowState, key: str) -> WorkflowState:
        return WorkflowState(
            state.pinned_today | {key}, state.snoozed, state.observed
        )

    @staticmethod
    def _unpin(state: WorkflowState, key: str) -> WorkflowState:
        return WorkflowState(
            state.pinned_today - {key}, state.snoozed, state.observed
        )

    @staticmethod
    def _snooze(state: WorkflowState, key: str, until: date) -> WorkflowState:
        return WorkflowState(
            state.pinned_today,
            tuple(sorted(
                {record for record in state.snoozed if record.key != key}
                | {SnoozeRecord(key, until)}
            )),
            state.observed,
        )

    @staticmethod
    def _wake(state: WorkflowState, key: str) -> WorkflowState:
        return WorkflowState(
            state.pinned_today,
            tuple(record for record in state.snoozed if record.key != key),
            state.observed,
        )

    @classmethod
    def _validate_legacy_expansion(
        cls, legacy_key: str | None, replacement_keys: tuple[str, ...]
    ) -> None:
        if legacy_key is None:
            if replacement_keys:
                raise ValueError("Workflow legacy-key expansion is invalid.")
            return
        cls._require_content_key(legacy_key)
        if not replacement_keys:
            raise ValueError("Workflow legacy-key expansion is invalid.")
        for key in replacement_keys:
            cls._require_content_key(key)

    @staticmethod
    def _expand_legacy_key(
        state: WorkflowState,
        legacy_key: str | None,
        replacement_keys: tuple[str, ...],
    ) -> WorkflowState:
        if legacy_key is None:
            return state
        pins = state.pinned_today
        if legacy_key in pins:
            pins = frozenset((pins - {legacy_key}) | set(replacement_keys))
        snoozes = state.snoozed
        legacy_snooze = next(
            (record for record in snoozes if record.key == legacy_key), None
        )
        if legacy_snooze is not None:
            snoozes = tuple(sorted(
                tuple(record for record in snoozes if record.key != legacy_key)
                + tuple(
                    SnoozeRecord(key, legacy_snooze.until)
                    for key in replacement_keys
                )
            ))
        return WorkflowState(pins, snoozes, state.observed)

    def reconcile(
        self, observations: tuple[TaskObservation, ...], today: date
    ) -> tuple[WorkflowState, dict[str, ObservedTask]]:
        if not isinstance(today, date):
            raise ValueError("Workflow reconciliation requires a date.")
        current = tuple(observations)
        self._validate_observations(current)
        state, mode = self._read_current()
        first_snapshot = not state.observed
        previous_by_location = {record.location: record for record in state.observed}
        previous_by_content: dict[str, list[ObservedRecord]] = {}
        for record in state.observed:
            previous_by_content.setdefault(record.content, []).append(record)

        next_records: list[ObservedRecord] = []
        content_counts: dict[str, int] = {}
        for item in current:
            content_counts[item.content] = content_counts.get(item.content, 0) + 1
        tasks: dict[str, ObservedTask] = {}
        for item in current:
            same_location = previous_by_location.get(item.location)
            same_content = previous_by_content.get(item.content, [])
            if first_snapshot:
                unchanged_since = min(item.source_modified_on, today)
                change = ""
            elif same_location is not None and same_location.content == item.content:
                unchanged_since = same_location.unchanged_since
                change = ""
            elif same_content:
                unchanged_since = min(record.unchanged_since for record in same_content)
                change = ""
            elif same_location is not None:
                unchanged_since = today
                change = "changed"
            else:
                unchanged_since = today
                change = "new"
            record = ObservedRecord(item.location, item.content, unchanged_since)
            next_records.append(record)
            observed_task = ObservedTask(
                item.location, item.content, unchanged_since, change
            )
            tasks[item.location] = observed_task
            if content_counts[item.content] == 1:
                tasks[item.content] = observed_task

        next_state = WorkflowState(
            state.pinned_today,
            tuple(record for record in state.snoozed if record.until > today),
            tuple(sorted(next_records)),
        )
        self._write_atomically(next_state, 0o600 if mode is None else mode)
        return next_state, tasks

    @staticmethod
    def _require_content_key(key: str) -> None:
        if not _is_content_key(key):
            raise ValueError("Workflow key is invalid.")

    @staticmethod
    def _validate_observations(observations: tuple[TaskObservation, ...]) -> None:
        locations: set[str] = set()
        for item in observations:
            if (
                not isinstance(item, TaskObservation)
                or not _is_location_key(item.location)
                or not _is_content_key(item.content)
                or not isinstance(item.source_modified_on, date)
                or (MANAGED_KEY_RE.fullmatch(item.content) and item.location != item.content)
                or item.location in locations
            ):
                raise ValueError("Workflow observations are invalid.")
            locations.add(item.location)

    def _mutate(self, update) -> None:
        state, mode = self._read_current()
        self._write_atomically(update(state), 0o600 if mode is None else mode)

    def _read_current(self) -> tuple[WorkflowState, int | None]:
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, _safe_read_flags())
        except FileNotFoundError:
            return EMPTY_STATE, None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ValueError("Workflow state path must be a regular file.") from error
            raise ValueError("Workflow state could not be read safely.") from error
        try:
            stat_result = os.fstat(descriptor)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValueError("Workflow state path must be a regular file.")
            data = os.read(descriptor, stat_result.st_size + 1)
        except OSError as error:
            raise ValueError("Workflow state could not be read safely.") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        try:
            payload = json.loads(data.decode("utf-8"), object_pairs_hook=_json_object)
            state = _state_from_payload(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Workflow state is malformed.") from error
        return state, stat_result.st_mode & 0o7777

    def _write_atomically(self, state: WorkflowState, mode: int) -> None:
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": 1,
                    "pinned_today": sorted(state.pinned_today),
                    "snoozed": [
                        {"key": record.key, "until": record.until.isoformat()}
                        for record in state.snoozed
                    ],
                    "observed": [
                        {
                            "location": record.location,
                            "content": record.content,
                            "unchanged_since": record.unchanged_since.isoformat(),
                        }
                        for record in state.observed
                    ],
                },
                separators=(",", ":"),
            )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
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
