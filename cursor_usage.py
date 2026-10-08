"""Read an explicitly configured Cursor Enterprise Admin spending API.

No browser/session credentials or client authentication databases are read.
The endpoint exposes current-cycle spending, not personal-plan quota or Bot meters.
"""

from dataclasses import dataclass
from decimal import Decimal, DecimalException
import os
from pathlib import Path
import re
import stat
import time

import requests


CURSOR_SPEND_URL = "https://api.cursor.com/teams/spend"
CURSOR_REFRESH_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class CursorUsageSummary:
    connected: bool = False
    included_used: Decimal | None = None
    on_demand_used: Decimal | None = None
    cycle_started_at: float | None = None
    fetched_at: float | None = None
    # The current /teams/spend schema does not expose these fields.
    included_allowance: Decimal | None = None
    plan_name: str | None = None
    resets_at: float | None = None
    grok_bot_used: Decimal | None = None
    error: str = "Not connected · needs Enterprise Admin API key"


def _read_key_file(path: Path) -> str | None:
    """Read only a small, regular, owner-only, non-symlink key file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 4096):
                return None
            return handle.read(4097).strip()
    except (OSError, UnicodeError):
        return None


def _number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (DecimalException, ValueError):
        return None
    # Bound both size and precision before arithmetic/formatting. These fields
    # are cents or epoch milliseconds, never enormous/tiny scientific values.
    if not result.is_finite() or result < 0 or result > Decimal("1e15"):
        return None
    return result if result == 0 or result.adjusted() >= -6 else None


def parse_cursor_spend(payload, account_email: str) -> CursorUsageSummary:
    """Keep only spending for one exact member; never retain identity/raw data."""
    if not isinstance(payload, dict) or not isinstance(payload.get("teamMemberSpend"), list):
        return CursorUsageSummary(error="Cursor spending response unavailable")
    matches = [item for item in payload["teamMemberSpend"]
               if isinstance(item, dict) and isinstance(item.get("email"), str)
               and item["email"].casefold() == account_email.casefold()]
    if len(matches) != 1:
        return CursorUsageSummary(error="Cursor exact account match unavailable")
    member = matches[0]
    on_demand_cents = _number(member.get("spendCents"))
    overall_cents = _number(member.get("overallSpendCents"))
    included = None
    if (on_demand_cents is not None and overall_cents is not None
            and overall_cents >= on_demand_cents):
        included = (overall_cents - on_demand_cents) / 100
    cycle_ms = _number(payload.get("subscriptionCycleStart"))
    # Reject out-of-range dates rather than letting rendering raise on them.
    cycle = float(cycle_ms / 1000) if cycle_ms is not None and 0 < cycle_ms < 253402300799000 else None
    return CursorUsageSummary(
        connected=True,
        included_used=included,
        on_demand_used=on_demand_cents / 100 if on_demand_cents is not None else None,
        cycle_started_at=cycle,
        fetched_at=time.time(),
        error="",
    )


def read_cursor_usage(*, environ=None, key_path: Path | None = None) -> CursorUsageSummary:
    env = os.environ if environ is None else environ
    if key_path is None:
        config = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        key_path = config / "claude-indicator" / "cursor-admin-api-key.txt"
    key = env.get("CURSOR_ADMIN_API_KEY", "").strip() or _read_key_file(key_path)
    if not key:
        return CursorUsageSummary()
    # Cloud Agent, xAI and session tokens are not substitutes for an Admin key.
    if not re.fullmatch(r"crsr_[A-Za-z0-9_-]+", key):
        return CursorUsageSummary(error="Not connected · requires Cursor Admin API key")
    account = env.get("CURSOR_ACCOUNT_EMAIL", "").strip()
    if len(account) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", account):
        return CursorUsageSummary(error="Not connected · set CURSOR_ACCOUNT_EMAIL")
    try:
        response = requests.post(
            CURSOR_SPEND_URL,
            auth=(key, ""),
            json={"searchTerm": account, "page": 1, "pageSize": 100},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code in (401, 403):
            return CursorUsageSummary(error="Cursor Enterprise Admin access required")
        if response.status_code == 429:
            return CursorUsageSummary(error="Cursor usage temporarily rate limited")
        if response.status_code != 200:
            return CursorUsageSummary(error="Cursor spending request unavailable")
        return parse_cursor_spend(response.json(), account)
    except (requests.RequestException, DecimalException, ValueError, TypeError, OverflowError):
        # Exceptions/bodies may contain credentials, email or other team data.
        return CursorUsageSummary(error="Cursor spending request unavailable")
