"""Exercise safe informational commands and Linux/display launch validation."""

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

import indicator_cli


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_information_commands_exit_before_widget_import(flag, monkeypatch, capsys):
    forbidden = ModuleType("claude_widget")
    forbidden.main = Mock(side_effect=AssertionError("Widget must not start"))
    monkeypatch.setitem(sys.modules, "claude_widget", forbidden)
    with pytest.raises(SystemExit) as exit_info:
        indicator_cli.main([flag])
    assert exit_info.value.code == 0
    assert "claude-indicator" in capsys.readouterr().out
    forbidden.main.assert_not_called()


def test_launch_requires_linux(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(SystemExit) as exit_info:
        indicator_cli.main([])
    assert exit_info.value.code == 2
    assert "Linux" in capsys.readouterr().err


def test_launch_requires_display(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        indicator_cli.main([])
    assert exit_info.value.code == 2
    assert "DISPLAY" in capsys.readouterr().err


def test_launch_delegates_once_after_validation(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":test")
    widget = ModuleType("claude_widget")
    widget.main = Mock(return_value=0)
    monkeypatch.setitem(sys.modules, "claude_widget", widget)
    assert indicator_cli.main([]) == 0
    widget.main.assert_called_once_with()
