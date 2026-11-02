#!/usr/bin/env python3
"""Capture only Claude Code quota fields; optionally forward its status line unchanged.

Configure statusLine.command as:
python3 /path/to/scripts/claude_statusline.py --forward 'your existing command'
No credentials, prompts, or transcript paths are saved. No network calls are made.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def capture(payload, destination):
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return
    # Whitelist quota fields rather than retaining the session payload.
    clean = {}
    for name in ("five_hour", "seven_day"):
        window = limits.get(name)
        if isinstance(window, dict):
            clean[name] = {key: window.get(key) for key in ("used_percentage", "resets_at")}
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".quota-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"rate_limits": clean, "fetched_at": time.time()}, output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forward", help="Existing trusted status-line shell command")
    args = parser.parse_args()
    raw = sys.stdin.read()
    try:
        capture(json.loads(raw), Path.home() / ".claude" / "indicator_quota.json")
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # A collector failure must not break the existing terminal display.
    if args.forward:
        return subprocess.run(args.forward, shell=True, input=raw, text=True).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
