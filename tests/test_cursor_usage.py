from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from cursor_usage import CURSOR_SPEND_URL, parse_cursor_spend, read_cursor_usage


ACCOUNT = "member@example.invalid"
KEY = "crsr_offline_test_key"


def payload(**member):
    return {"subscriptionCycleStart": 1790812800000, "teamMemberSpend": [
        {"email": ACCOUNT, "spendCents": 125, "overallSpendCents": 975, **member},
        {"email": "other@example.invalid", "spendCents": 90000, "overallSpendCents": 99999},
    ]}


def test_exact_member_spend_semantics_and_unsupported_fields():
    summary = parse_cursor_spend(payload(
        email=ACCOUNT.upper(), monthlyLimitDollars=100, hardLimitOverrideDollars=200,
        effectivePerUserLimitDollars=300, model="grok", application_type="grok_bot",
        planName="untrusted undocumented field", resetsAt=9999999999,
    ), ACCOUNT)
    assert summary.connected
    assert summary.included_used == Decimal("8.50")
    assert summary.on_demand_used == Decimal("1.25")
    assert summary.cycle_started_at == 1790812800
    assert summary.fetched_at is not None
    assert summary.included_allowance is None
    assert summary.plan_name is None
    assert summary.resets_at is None
    assert summary.grok_bot_used is None
    assert ACCOUNT not in repr(summary) and "other@" not in repr(summary)


def test_documented_real_zero_is_distinct_from_unknown():
    summary = parse_cursor_spend(payload(spendCents=0, overallSpendCents=0), ACCOUNT)
    assert summary.on_demand_used == Decimal(0)
    assert summary.included_used == Decimal(0)
    assert summary.grok_bot_used is None


@pytest.mark.parametrize("bad", [None, -1, True, "invalid", "NaN", "Infinity", {}, [],
                                  "1e1000000", "1e-1000000", "9" * 100, 10 ** 20])
def test_invalid_spend_stays_unavailable(bad):
    summary = parse_cursor_spend(payload(spendCents=bad), ACCOUNT)
    assert summary.on_demand_used is None
    assert summary.included_used is None


def test_inconsistent_total_does_not_make_negative_included_usage():
    summary = parse_cursor_spend(payload(spendCents=100, overallSpendCents=50), ACCOUNT)
    assert summary.on_demand_used == Decimal(1)
    assert summary.included_used is None


@pytest.mark.parametrize("data", [None, [], {}, {"teamMemberSpend": {}},
                                  {"teamMemberSpend": [{"email": "substring" + ACCOUNT}]},
                                  {"teamMemberSpend": [{"email": ACCOUNT}, {"email": ACCOUNT}]}])
def test_missing_or_ambiguous_exact_member_fails_closed(data):
    summary = parse_cursor_spend(data, ACCOUNT)
    assert not summary.connected
    assert summary.included_used is None and summary.on_demand_used is None


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity", 253402300799000, True])
def test_invalid_cycle_date_is_not_a_reset(value):
    data = payload()
    data["subscriptionCycleStart"] = value
    summary = parse_cursor_spend(data, ACCOUNT)
    assert summary.cycle_started_at is None and summary.resets_at is None


def test_disconnected_without_key_makes_no_request(tmp_path):
    with patch("cursor_usage.requests.post") as post:
        summary = read_cursor_usage(environ={}, key_path=tmp_path / "missing")
    post.assert_not_called()
    assert not summary.connected and "needs Enterprise Admin API key" in summary.error


@pytest.mark.parametrize("env,reason", [
    ({"CURSOR_ADMIN_API_KEY": "session_token", "CURSOR_ACCOUNT_EMAIL": ACCOUNT}, "Admin API key"),
    ({"CURSOR_ADMIN_API_KEY": "key_unsupported_prefix", "CURSOR_ACCOUNT_EMAIL": ACCOUNT}, "Admin API key"),
    ({"CURSOR_API_KEY": KEY, "CURSOR_ACCOUNT_EMAIL": ACCOUNT}, "Admin API key"),
    ({"CURSOR_ADMIN_API_KEY": KEY}, "CURSOR_ACCOUNT_EMAIL"),
    ({"CURSOR_ADMIN_API_KEY": KEY, "CURSOR_ACCOUNT_EMAIL": "bad email"}, "CURSOR_ACCOUNT_EMAIL"),
])
def test_only_explicit_admin_key_and_target_email_can_connect(tmp_path, env, reason):
    with patch("cursor_usage.requests.post") as post:
        summary = read_cursor_usage(environ=env, key_path=tmp_path / "missing")
    post.assert_not_called()
    assert not summary.connected and reason in summary.error


def test_fixed_official_destination_auth_filtered_target_and_no_redirects(tmp_path):
    response = Mock(status_code=200)
    response.json.return_value = payload()
    with patch("cursor_usage.requests.post", return_value=response) as post:
        summary = read_cursor_usage(environ={"CURSOR_ADMIN_API_KEY": KEY,
                                            "CURSOR_ACCOUNT_EMAIL": ACCOUNT},
                                    key_path=tmp_path / "missing")
    post.assert_called_once_with(CURSOR_SPEND_URL, auth=(KEY, ""),
                                json={"searchTerm": ACCOUNT, "page": 1, "pageSize": 100},
                                timeout=10, allow_redirects=False)
    assert summary.connected


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
def test_response_errors_never_echo_secrets_or_team_data(tmp_path, status):
    response = Mock(status_code=status, text=f"{KEY} {ACCOUNT}")
    with patch("cursor_usage.requests.post", return_value=response):
        summary = read_cursor_usage(environ={"CURSOR_ADMIN_API_KEY": KEY,
                                            "CURSOR_ACCOUNT_EMAIL": ACCOUNT},
                                    key_path=tmp_path / "missing")
    assert not summary.connected
    assert KEY not in repr(summary) and ACCOUNT not in repr(summary)
    response.json.assert_not_called()


@pytest.mark.parametrize("error", [requests.RequestException(f"{KEY} {ACCOUNT}"),
                                   ValueError(f"{KEY} {ACCOUNT}")])
def test_request_or_json_errors_are_sanitized(tmp_path, error):
    with patch("cursor_usage.requests.post", side_effect=error):
        summary = read_cursor_usage(environ={"CURSOR_ADMIN_API_KEY": KEY,
                                            "CURSOR_ACCOUNT_EMAIL": ACCOUNT},
                                    key_path=tmp_path / "missing")
    assert not summary.connected
    assert KEY not in summary.error and ACCOUNT not in summary.error


def test_private_key_file_and_xdg_location(tmp_path):
    key_file = tmp_path / "claude-indicator" / "cursor-admin-api-key.txt"
    key_file.parent.mkdir(mode=0o700)
    key_file.write_text(KEY + "\n")
    key_file.chmod(0o600)
    response = Mock(status_code=200)
    response.json.return_value = payload()
    with patch("cursor_usage.requests.post", return_value=response):
        summary = read_cursor_usage(environ={"XDG_CONFIG_HOME": str(tmp_path),
                                            "CURSOR_ACCOUNT_EMAIL": ACCOUNT})
    assert summary.connected


@pytest.mark.parametrize("kind", ["public", "symlink", "directory", "oversize", "other-owner", "fifo"])
def test_unsafe_key_files_are_ignored_without_network(tmp_path, kind):
    key_file = tmp_path / "key"
    if kind == "directory":
        key_file.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_text(KEY)
        target.chmod(0o600)
        key_file.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(key_file, mode=0o600)
    else:
        key_file.write_text("k" * 4097 if kind == "oversize" else KEY)
        key_file.chmod(0o644 if kind == "public" else 0o600)
    with patch("cursor_usage.requests.post") as post:
        if kind == "other-owner":
            actual = key_file.stat()
            fake = Mock(st_mode=actual.st_mode, st_uid=os.getuid() + 1, st_size=actual.st_size)
            with patch("cursor_usage.os.fstat", return_value=fake):
                summary = read_cursor_usage(environ={"CURSOR_ACCOUNT_EMAIL": ACCOUNT}, key_path=key_file)
        else:
            summary = read_cursor_usage(environ={"CURSOR_ACCOUNT_EMAIL": ACCOUNT}, key_path=key_file)
    post.assert_not_called()
    assert not summary.connected
