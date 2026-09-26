#!/usr/bin/env python3
"""Install or launch the widget's persistent user service and desktop autostart."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

SERVICE = "claude-indicator.service"
DISPLAY_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")


def systemd_quote(value, *, command=False):
    value = str(value)
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Paths must not contain newline or NUL characters")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def desktop_quote(value):
    value = str(value)
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Paths must not contain newline or NUL characters")
    # Exec has its own quoting layer, then desktop-file string unescaping.
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value.replace("\\", "\\\\").replace("%", "%%") + '"'


def service_text(python, checkout, library_path=None):
    environment = "Environment=PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1\n"
    if library_path:
        environment += "Environment=" + systemd_quote("LD_LIBRARY_PATH=" + str(library_path)) + "\n"
    return f"""[Unit]
Description=Claude usage desktop indicator
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
NotifyAccess=main
ExecStart={systemd_quote(python, command=True)} {systemd_quote(checkout / 'claude_widget.py', command=True)}
WorkingDirectory={str(checkout).replace('%', '%%')}
{environment}Restart=on-failure
RestartSec=5
WatchdogSec=90
WatchdogSignal=SIGABRT
TimeoutAbortSec=10
LimitCORE=0
TimeoutStartSec=120
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=claude-indicator
"""


def desktop_text(python, checkout):
    return f"""[Desktop Entry]
Type=Application
Name=Claude Usage Widget
Comment=Start the supervised Claude usage desktop indicator
Exec={desktop_quote(python)} {desktop_quote(checkout / 'scripts/indicator_service.py')} launch
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def install(python, checkout, config_home, library_path=None):
    python, checkout = Path(python).absolute(), Path(checkout).resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Python interpreter must be an executable file")
    if not (checkout / "claude_widget.py").is_file():
        raise ValueError("Checkout must contain claude_widget.py")
    # Render everything before replacing either installed file.
    unit = service_text(python, checkout, library_path)
    desktop = desktop_text(python, checkout)
    paths = (config_home / "systemd/user" / SERVICE, config_home / "autostart/claude-widget.desktop")
    for path, content in zip(paths, (unit, desktop)):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(content)
        temp.replace(path)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return paths


def launch():
    present = [key for key in DISPLAY_ENV if os.environ.get(key)]
    if not any(key in present for key in ("DISPLAY", "WAYLAND_DISPLAY")):
        raise RuntimeError("Launch requires a graphical session (DISPLAY or WAYLAND_DISPLAY)")
    missing = [key for key in DISPLAY_ENV if key not in present]
    if missing:
        subprocess.run(["systemctl", "--user", "unset-environment", *missing], check=True)
    subprocess.run(["systemctl", "--user", "import-environment", *present], check=True)
    subprocess.run(["systemctl", "--user", "start", SERVICE], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    installer = subparsers.add_parser("install")
    installer.add_argument("--python", type=Path, default=Path(sys.executable))
    installer.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[1])
    installer.add_argument("--library-path", type=Path)
    installer.add_argument("--config-home", type=Path, default=Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")))
    subparsers.add_parser("launch")
    args = parser.parse_args()
    if args.command == "install":
        for path in install(args.python, args.checkout, args.config_home, args.library_path):
            print(path)
    else:
        launch()


if __name__ == "__main__":
    main()
