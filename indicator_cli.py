"""Command-line entry point; informational commands do not load Qt or credentials."""

import argparse
import os
import sys

__version__ = "0.1.0b1"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="claude-indicator",
        description="Local Linux desktop indicator for AI subscription usage and system activity.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("The beta supports Linux with X11 or XWayland only.")
    if not (os.environ.get("DISPLAY") or os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
        parser.error("A graphical X11 or XWayland session with DISPLAY is required.")
    from claude_widget import main as run_widget

    return run_widget()


if __name__ == "__main__":
    main()
