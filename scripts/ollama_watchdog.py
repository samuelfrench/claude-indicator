#!/usr/bin/env python3
"""Restart ollama when its scheduler has been wedged for a quarter of an hour.

Ollama 0.32.14 can deadlock its scheduler while the HTTP layer and the
llama-server backend both stay healthy: cheap handlers answer instantly, but
inference never returns and a model sits pinned in VRAM long past its
keep-alive expiry. This watchdog detects that state without paying for a
generation, and restarts the service only after it has persisted.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
STATE_PATH = os.environ.get("OLLAMA_WATCHDOG_STATE", "/run/ollama-watchdog.state")
READ_TIMEOUT_S = 5
PROBE_TIMEOUT_S = 60
# A healthy scheduler evicts within seconds of expiry; allow for poll jitter.
EXPIRY_GRACE_S = 60
STUCK_AFTER_S = 15 * 60


def expiry_lag_s(payload: dict, now: float) -> float | None:
    """Seconds since the most recent keep-alive expiry passed, or None if unknown."""
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        return None
    lags: list[float] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        raw = model.get("expires_at")
        if not isinstance(raw, str):
            continue
        # Go renders nanoseconds; datetime accepts at most microseconds.
        normalized = re.sub(r"\.(\d{1,9})", lambda m: "." + m.group(1)[:6], raw)
        try:
            moment = datetime.datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        lags.append(now - moment.timestamp())
    if not lags:
        return None
    return min(lags)


def read_ps() -> dict:
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=READ_TIMEOUT_S) as resp:
        return json.load(resp)


def probe_body(model: str, remaining_s: float) -> bytes:
    """Build a no-token load request that leaves the existing expiry intact."""
    keep_alive = max(1, int(remaining_s))
    return json.dumps(
        {"model": model, "prompt": "", "keep_alive": f"{keep_alive}s"}
    ).encode()


def probe_scheduler(model: str, remaining_s: float) -> bool:
    """Ask the scheduler to touch an already-loaded model. No tokens generated."""
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=probe_body(model, remaining_s),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def evaluate(payload: dict, now: float, probe) -> tuple[bool, str]:
    lag = expiry_lag_s(payload, now)
    if lag is None:
        return True, "idle"
    if lag > EXPIRY_GRACE_S:
        return False, f"model expired {lag / 60:.1f}m ago and was never evicted"
    if probe():
        return True, "probe ok"
    return False, f"scheduler probe hung past {PROBE_TIMEOUT_S}s"


def update_state(state: dict, healthy: bool, now: float) -> tuple[dict, bool]:
    if healthy:
        return {}, False
    since = state.get("unhealthy_since")
    if not isinstance(since, (int, float)):
        return {"unhealthy_since": now}, False
    if now - since >= STUCK_AFTER_S:
        return {}, True
    return {"unhealthy_since": float(since)}, False


def load_state() -> dict:
    try:
        with open(STATE_PATH) as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state: dict) -> None:
    tmp = f"{STATE_PATH}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        log(f"state write failed: {exc}")


def log(message: str) -> None:
    print(f"ollama-watchdog: {message}", flush=True)


def main() -> int:
    now = time.time()
    try:
        payload = read_ps()
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        # systemd's Restart=always already covers a dead or crashing server.
        log(f"/api/ps unavailable ({type(exc).__name__}); leaving it to systemd")
        return 0

    models = payload.get("models") or []
    name = ""
    if isinstance(models, list) and models and isinstance(models[0], dict):
        name = str(models[0].get("model") or models[0].get("name") or "")
    lag = expiry_lag_s(payload, now)
    remaining_s = 0.0 if lag is None else -lag
    healthy, reason = evaluate(
        payload, now, lambda: probe_scheduler(name, remaining_s)
    )
    state, should_restart = update_state(load_state(), healthy, now)
    save_state(state)

    if healthy:
        return 0
    if not should_restart:
        stuck_for = now - state.get("unhealthy_since", now)
        log(f"unhealthy: {reason} (stuck {stuck_for / 60:.1f}m of {STUCK_AFTER_S // 60}m)")
        return 0

    log(f"restarting ollama after {STUCK_AFTER_S // 60}m stuck: {reason}")
    result = subprocess.run(
        ["systemctl", "restart", "ollama"], capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"restart failed rc={result.returncode}: {result.stderr.strip()}")
        return 1
    log("restart complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
