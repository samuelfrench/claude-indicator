"""Strict local persistence for Smart TODO workflow choices and scan history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
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
    action: str = ""
    legacy_actions: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class SnoozeRecord:
    key: str
    until: date


@dataclass(frozen=True, order=True)
class ObservedRecord:
    location: str
    content: str
    unchanged_since: date
    action: str = ""
    sequence: int = -1


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
    legacy_schema = {"location", "content", "unchanged_since"}
    current_schema = legacy_schema | {"action", "sequence"}
    if not isinstance(value, dict) or frozenset(value) not in {
        frozenset(legacy_schema), frozenset(current_schema)
    }:
        raise ValueError("Workflow state has an unsupported schema.")
    location = value["location"]
    content = value["content"]
    if not _is_location_key(location) or not _is_content_key(content):
        raise ValueError("Workflow state has invalid keys.")
    if MANAGED_KEY_RE.fullmatch(str(content)) and location != content:
        raise ValueError("Workflow state has invalid keys.")
    if set(value) == legacy_schema:
        return ObservedRecord(location, content, _parse_date(value["unchanged_since"]))
    action = value["action"]
    sequence = value["sequence"]
    if (
        not _is_content_key(action)
        or type(sequence) is not int
        or sequence < 0
        or (MANAGED_KEY_RE.fullmatch(str(content)) and action != content)
    ):
        raise ValueError("Workflow state has invalid observation identity.")
    return ObservedRecord(
        location, content, _parse_date(value["unchanged_since"]), action, sequence
    )


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
    current_records = [record for record in observed if record.action]
    if current_records and len(current_records) != len(observed):
        raise ValueError("Workflow state mixes observation schemas.")
    if current_records and (
        len({record.action for record in observed}) != len(observed)
        or sorted(record.sequence for record in observed) != list(range(len(observed)))
    ):
        raise ValueError("Workflow state has noncanonical observation identities.")
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
        if (
            not isinstance(replacement_keys, tuple)
            or replacement_keys != tuple(sorted(set(replacement_keys)))
        ):
            raise ValueError("Workflow legacy-key expansion is invalid.")

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

        action_matches = self._match_actions(state.observed, current)
        legacy_aliases = self._legacy_aliases(
            state.observed, current, action_matches
        )
        next_records: list[ObservedRecord] = []
        content_counts: dict[str, int] = {}
        for item in current:
            content_counts[item.content] = content_counts.get(item.content, 0) + 1
        tasks: dict[str, ObservedTask] = {}
        for sequence, item in enumerate(current):
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
            action = action_matches.get(sequence)
            if item.content.startswith("managed:"):
                action = item.content
            if action is None:
                action = "source:" + secrets.token_hex(32)
            record = ObservedRecord(
                item.location, item.content, unchanged_since, action, sequence
            )
            next_records.append(record)
            observed_task = ObservedTask(
                item.location,
                item.content,
                unchanged_since,
                change,
                action,
                legacy_aliases.get(sequence, ()),
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
    def _match_actions(
        previous: tuple[ObservedRecord, ...],
        current: tuple[TaskObservation, ...],
    ) -> dict[int, str]:
        """Reuse opaque identities only when scan history identifies one row."""
        if not previous or any(not record.action for record in previous):
            return {}
        old = sorted(previous, key=lambda record: record.sequence)
        old_by_content: dict[str, list[int]] = {}
        new_by_content: dict[str, list[int]] = {}
        for index, record in enumerate(old):
            old_by_content.setdefault(record.content, []).append(index)
        for index, observation in enumerate(current):
            new_by_content.setdefault(observation.content, []).append(index)

        matches: dict[int, str] = {}
        used_old: set[int] = set()
        for content, new_indices in new_by_content.items():
            old_indices = old_by_content.get(content, [])
            if len(old_indices) == len(new_indices) == 1:
                old_index = old_indices[0]
                matches[new_indices[0]] = old[old_index].action
                used_old.add(old_index)
                continue

            old_contexts = WorkflowStore._content_contexts(
                tuple(record.content for record in old), old_indices
            )
            new_contexts = WorkflowStore._content_contexts(
                tuple(item.content for item in current), new_indices
            )
            for context in set(old_contexts) & set(new_contexts):
                old_candidates = old_contexts[context]
                new_candidates = new_contexts[context]
                if len(old_candidates) == len(new_candidates) == 1:
                    old_index = old_candidates[0]
                    matches[new_candidates[0]] = old[old_index].action
                    used_old.add(old_index)

            if len(old_indices) == len(new_indices):
                old_locations = {
                    old[index].location: index
                    for index in old_indices
                    if index not in used_old
                }
                for new_index in new_indices:
                    if new_index in matches:
                        continue
                    old_index = old_locations.get(current[new_index].location)
                    if old_index is not None:
                        matches[new_index] = old[old_index].action
                        used_old.add(old_index)

        # A unique same-location content edit retains its identity. Never use this
        # fallback when either content still participates in a duplicate edit.
        for new_index, item in enumerate(current):
            if new_index in matches:
                continue
            old_record = next(
                (
                    (index, record)
                    for index, record in enumerate(old)
                    if record.location == item.location and index not in used_old
                ),
                None,
            )
            if old_record is None:
                continue
            old_index, record = old_record
            if (
                len(old_by_content.get(record.content, ())) == 1
                and len(new_by_content.get(item.content, ())) == 1
                and record.content not in new_by_content
                and item.content not in old_by_content
            ):
                matches[new_index] = record.action
                used_old.add(old_index)
        return matches

    @staticmethod
    def _legacy_aliases(
        previous: tuple[ObservedRecord, ...],
        current: tuple[TaskObservation, ...],
        action_matches: dict[int, str],
    ) -> dict[int, tuple[str, ...]]:
        """Expose old aliases only when history proves the original row."""
        if not previous:
            return {}

        def ordinal_alias(content: str, occurrence: int) -> str:
            identity = f"selected-row\0{content}\0{occurrence}"
            return "source:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

        aliases: dict[int, tuple[str, ...]] = {}
        if all(record.action for record in previous):
            old = sorted(previous, key=lambda record: record.sequence)
            old_by_content: dict[str, list[int]] = {}
            for index, record in enumerate(old):
                old_by_content.setdefault(record.content, []).append(index)
            by_action: dict[str, tuple[str, ...]] = {}
            for content, indices in old_by_content.items():
                if MANAGED_KEY_RE.fullmatch(content):
                    continue
                for occurrence, old_index in enumerate(indices, start=1):
                    row_aliases = [content]
                    if len(indices) > 1:
                        row_aliases.append(ordinal_alias(content, occurrence))
                    by_action[old[old_index].action] = tuple(row_aliases)
            for new_index, action in action_matches.items():
                if action in by_action:
                    aliases[new_index] = by_action[action]
            return aliases

        previous_by_content: dict[str, list[ObservedRecord]] = {}
        current_by_content: dict[str, list[int]] = {}
        for record in previous:
            previous_by_content.setdefault(record.content, []).append(record)
        for index, item in enumerate(current):
            current_by_content.setdefault(item.content, []).append(index)
        for content, new_indices in current_by_content.items():
            if MANAGED_KEY_RE.fullmatch(content):
                continue
            old_records = previous_by_content.get(content, [])
            locations_unchanged = {
                record.location for record in old_records
            } == {current[index].location for index in new_indices}
            unique_move = len(old_records) == len(new_indices) == 1
            if len(old_records) != len(new_indices) or not (
                locations_unchanged or unique_move
            ):
                continue
            for occurrence, new_index in enumerate(new_indices, start=1):
                row_aliases = [content]
                if len(new_indices) > 1:
                    row_aliases.append(ordinal_alias(content, occurrence))
                aliases[new_index] = tuple(row_aliases)
        return aliases

    @staticmethod
    def _content_contexts(
        contents: tuple[str, ...], indices: list[int]
    ) -> dict[tuple[str, str], list[int]]:
        contexts: dict[tuple[str, str], list[int]] = {}
        for index in indices:
            content = contents[index]
            before = "<start>"
            after = "<end>"
            for candidate in range(index - 1, -1, -1):
                if contents[candidate] != content:
                    before = contents[candidate]
                    break
            for candidate in range(index + 1, len(contents)):
                if contents[candidate] != content:
                    after = contents[candidate]
                    break
            contexts.setdefault((before, after), []).append(index)
        return contexts

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
                        dict(
                            {
                                "location": record.location,
                                "content": record.content,
                                "unchanged_since": record.unchanged_since.isoformat(),
                            },
                            **(
                                {
                                    "action": record.action,
                                    "sequence": record.sequence,
                                }
                                if record.action
                                else {}
                            ),
                        )
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
