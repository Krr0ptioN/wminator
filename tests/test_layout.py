"""Tests for i3nator.layout — recursive i3 layout engine."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from i3nator.exceptions import LayoutError
from i3nator.layout import (
    _apply_ratios,
    _cmd,
    _collect_ratios,
    _set_container_layout,
    _split_direction,
    apply_layout,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(success: bool = True) -> MagicMock:
    """Create a mock i3ipc Connection whose command() returns reply objects."""
    conn = MagicMock(spec=["command"])
    reply = MagicMock()
    reply.success = success
    reply.error = "mock error" if not success else None
    conn.command.return_value = [reply]
    return conn


def _commands_sent(conn: MagicMock) -> list[str]:
    """Extract the list of i3 command strings sent via conn.command(...)."""
    return [c.args[0] for c in conn.command.call_args_list]


# ---------------------------------------------------------------------------
# _split_direction (pure function)
# ---------------------------------------------------------------------------


class TestSplitDirection:
    def test_explicit_horizontal(self) -> None:
        assert _split_direction({"split": "horizontal"}) == "h"

    def test_explicit_vertical(self) -> None:
        assert _split_direction({"split": "vertical"}) == "v"

    def test_layout_splith(self) -> None:
        assert _split_direction({"layout": "splith"}) == "h"

    def test_layout_splitv(self) -> None:
        assert _split_direction({"layout": "splitv"}) == "v"

    def test_layout_stacked(self) -> None:
        assert _split_direction({"layout": "stacked"}) == "v"

    def test_layout_tabbed(self) -> None:
        assert _split_direction({"layout": "tabbed"}) == "v"

    def test_default_is_horizontal(self) -> None:
        assert _split_direction({}) == "h"

    def test_explicit_split_takes_precedence(self) -> None:
        # split key wins over layout key
        assert _split_direction({"split": "vertical", "layout": "splith"}) == "v"


# ---------------------------------------------------------------------------
# _collect_ratios (pure function)
# ---------------------------------------------------------------------------


class TestCollectRatios:
    def test_no_ratios_returns_empty(self) -> None:
        children = [
            {"window": {"command": "a"}},
            {"window": {"command": "b"}},
        ]
        assert _collect_ratios(children) == []

    def test_all_ratios_set(self) -> None:
        children = [
            {"window": {"command": "a", "ratio": 30}},
            {"window": {"command": "b", "ratio": 70}},
        ]
        assert _collect_ratios(children) == [30, 70]

    def test_partial_ratios(self) -> None:
        children = [
            {"window": {"command": "a", "ratio": 60}},
            {"window": {"command": "b"}},
        ]
        result = _collect_ratios(children)
        assert result == [60, None]

    def test_container_children(self) -> None:
        children = [
            {"container": {"ratio": 40, "children": []}},
            {"container": {"ratio": 60, "children": []}},
        ]
        assert _collect_ratios(children) == [40, 60]

    def test_mixed_window_container(self) -> None:
        children = [
            {"window": {"command": "a", "ratio": 50}},
            {"container": {"ratio": 50, "children": []}},
        ]
        assert _collect_ratios(children) == [50, 50]


# ---------------------------------------------------------------------------
# _cmd
# ---------------------------------------------------------------------------


class TestCmd:
    @patch("i3nator.layout.time.sleep")
    def test_sends_command(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        _cmd(conn, "split h")
        conn.command.assert_called_once_with("split h")

    @patch("i3nator.layout.time.sleep")
    def test_sleeps_after_command(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        _cmd(conn, "split h")
        mock_sleep.assert_called_once()

    @patch("i3nator.layout.time.sleep")
    def test_failed_reply_does_not_raise(self, mock_sleep: Any) -> None:
        conn = _make_conn(success=False)
        # Should log a warning but not raise.
        _cmd(conn, "bad command")
        conn.command.assert_called_once_with("bad command")


# ---------------------------------------------------------------------------
# _set_container_layout
# ---------------------------------------------------------------------------


class TestSetContainerLayout:
    @patch("i3nator.layout.time.sleep")
    def test_stacked_layout(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        _set_container_layout(conn, "stacked", child_count=3)
        cmds = _commands_sent(conn)
        assert cmds == ["focus parent", "layout stacked", "focus child"]

    @patch("i3nator.layout.time.sleep")
    def test_tabbed_layout(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        _set_container_layout(conn, "tabbed", child_count=2)
        cmds = _commands_sent(conn)
        assert cmds == ["focus parent", "layout tabbed", "focus child"]


# ---------------------------------------------------------------------------
# _apply_ratios
# ---------------------------------------------------------------------------


class TestApplyRatios:
    @patch("i3nator.layout.time.sleep")
    def test_two_children_horizontal(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 30}},
            {"window": {"command": "b", "ratio": 70}},
        ]
        _apply_ratios(conn, children, [30.0, 70.0], "h")
        cmds = _commands_sent(conn)
        assert "focus parent" in cmds
        assert "resize set width 30 ppt" in cmds
        assert "resize set width 70 ppt" in cmds

    @patch("i3nator.layout.time.sleep")
    def test_two_children_vertical(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 40}},
            {"window": {"command": "b", "ratio": 60}},
        ]
        _apply_ratios(conn, children, [40.0, 60.0], "v")
        cmds = _commands_sent(conn)
        assert "resize set height 40 ppt" in cmds
        assert "resize set height 60 ppt" in cmds

    @patch("i3nator.layout.time.sleep")
    def test_navigates_between_children(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 33}},
            {"window": {"command": "b", "ratio": 33}},
            {"window": {"command": "c", "ratio": 34}},
        ]
        _apply_ratios(conn, children, [33.0, 33.0, 34.0], "h")
        cmds = _commands_sent(conn)
        # Should navigate right between children.
        assert cmds.count("focus right") == 2

    @patch("i3nator.layout.time.sleep")
    def test_navigates_down_for_vertical(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 50}},
            {"window": {"command": "b", "ratio": 50}},
        ]
        _apply_ratios(conn, children, [50.0, 50.0], "v")
        cmds = _commands_sent(conn)
        assert "focus down" in cmds

    @patch("i3nator.layout.time.sleep")
    def test_single_child_is_noop(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [{"window": {"command": "a", "ratio": 100}}]
        _apply_ratios(conn, children, [100.0], "h")
        conn.command.assert_not_called()

    @patch("i3nator.layout.time.sleep")
    def test_ratios_normalized_to_100(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 1}},
            {"window": {"command": "b", "ratio": 1}},
        ]
        _apply_ratios(conn, children, [1.0, 1.0], "h")
        cmds = _commands_sent(conn)
        assert "resize set width 50 ppt" in cmds

    @patch("i3nator.layout.time.sleep")
    def test_missing_ratios_filled(self, mock_sleep: Any) -> None:
        conn = _make_conn()
        children = [
            {"window": {"command": "a", "ratio": 60}},
            {"window": {"command": "b"}},
        ]
        _apply_ratios(conn, children, [60.0, None], "h")
        cmds = _commands_sent(conn)
        assert "resize set width 60 ppt" in cmds
        assert "resize set width 40 ppt" in cmds


# ---------------------------------------------------------------------------
# apply_layout (integration — mocks spawn_window)
# ---------------------------------------------------------------------------


class TestApplyLayout:
    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_single_window(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "terminal": "wezterm",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "vim"}},
                ],
            },
        }
        apply_layout(conn, config)
        mock_spawn.assert_called_once_with(
            conn,
            command="vim",
            window_type="terminal",
            terminal="wezterm",
            match=None,
            timeout=10.0,
        )

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_two_windows_horizontal_split(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "terminal": "wezterm",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "vim"}},
                    {"window": {"command": "htop"}},
                ],
            },
        }
        apply_layout(conn, config)
        assert mock_spawn.call_count == 2
        cmds = _commands_sent(conn)
        assert "split h" in cmds

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_vertical_split(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "vertical",
                "children": [
                    {"window": {"command": "a"}},
                    {"window": {"command": "b"}},
                ],
            },
        }
        apply_layout(conn, config)
        cmds = _commands_sent(conn)
        assert "split v" in cmds

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_app_window_type(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "horizontal",
                "children": [
                    {
                        "window": {
                            "command": "firefox",
                            "type": "app",
                            "match": {"class": "Firefox"},
                        }
                    },
                ],
            },
        }
        apply_layout(conn, config)
        mock_spawn.assert_called_once_with(
            conn,
            command="firefox",
            window_type="app",
            terminal="wezterm",
            match={"class": "Firefox"},
            timeout=10.0,
        )

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_custom_terminal(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "terminal": "alacritty",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "vim"}},
                ],
            },
        }
        apply_layout(conn, config)
        mock_spawn.assert_called_once_with(
            conn,
            command="vim",
            window_type="terminal",
            terminal="alacritty",
            match=None,
            timeout=10.0,
        )

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_default_terminal_is_wezterm(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "vim"}},
                ],
            },
        }
        apply_layout(conn, config)
        _, kwargs = mock_spawn.call_args
        assert kwargs["terminal"] == "wezterm"

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_empty_children_raises(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {"split": "horizontal", "children": []},
        }
        with pytest.raises(LayoutError, match="no children"):
            apply_layout(conn, config)

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_invalid_child_raises(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "horizontal",
                "children": [{"bogus": "data"}],
            },
        }
        with pytest.raises(LayoutError, match="neither"):
            apply_layout(conn, config)

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_stacked_container_sets_layout(
        self,
        mock_spawn: Any,
        mock_sleep: Any,
    ) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "layout": "stacked",
                "children": [
                    {"window": {"command": "a"}},
                    {"window": {"command": "b"}},
                ],
            },
        }
        apply_layout(conn, config)
        cmds = _commands_sent(conn)
        assert "focus parent" in cmds
        assert "layout stacked" in cmds
        assert "focus child" in cmds

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_ratios_applied(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "a", "ratio": 30}},
                    {"window": {"command": "b", "ratio": 70}},
                ],
            },
        }
        apply_layout(conn, config)
        cmds = _commands_sent(conn)
        assert "resize set width 30 ppt" in cmds
        assert "resize set width 70 ppt" in cmds

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_nested_container(self, mock_spawn: Any, mock_sleep: Any) -> None:
        """Calculus-style config: h-split with terminal + stacked container."""
        conn = _make_conn()
        config = {
            "name": "calculus",
            "terminal": "wezterm",
            "layout": {
                "split": "horizontal",
                "children": [
                    {
                        "window": {
                            "command": "tmuxinator start calculus",
                            "type": "terminal",
                            "ratio": 50,
                        }
                    },
                    {
                        "container": {
                            "layout": "stacked",
                            "ratio": 50,
                            "children": [
                                {
                                    "window": {
                                        "command": "zathura textbook.pdf",
                                        "type": "app",
                                        "match": {"class": "Zathura"},
                                    }
                                },
                                {
                                    "window": {
                                        "command": "zathura homework.pdf",
                                        "type": "app",
                                        "match": {"class": "Zathura", "title": "homework"},
                                    }
                                },
                            ],
                        }
                    },
                ],
            },
        }
        apply_layout(conn, config)

        # 3 windows total: 1 terminal + 2 zathura.
        assert mock_spawn.call_count == 3

        # The stacked sub-container should have set its layout.
        cmds = _commands_sent(conn)
        assert "layout stacked" in cmds

        # The top-level h-split should have been issued.
        assert "split h" in cmds

    @patch("i3nator.layout.time.sleep")
    @patch("i3nator.layout.spawn_window")
    def test_custom_timeout(self, mock_spawn: Any, mock_sleep: Any) -> None:
        conn = _make_conn()
        config = {
            "name": "test",
            "layout": {
                "split": "horizontal",
                "children": [
                    {"window": {"command": "slow-app", "type": "app", "timeout": 30.0}},
                ],
            },
        }
        apply_layout(conn, config)
        _, kwargs = mock_spawn.call_args
        assert kwargs["timeout"] == 30.0
