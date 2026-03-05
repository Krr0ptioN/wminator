"""Tests for i3nator.workspace — i3 workspace operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from i3nator.exceptions import WorkspaceError, WorkspaceOccupiedError
from i3nator.workspace import (
    clear_workspace,
    ensure_workspace_available,
    get_connection,
    get_focused_workspace,
    switch_to_workspace,
    workspace_is_empty,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn() -> MagicMock:
    """Create a mock i3ipc Connection with a configurable tree."""
    conn = MagicMock(spec=["command", "get_tree"])
    reply = MagicMock()
    reply.success = True
    reply.error = None
    conn.command.return_value = [reply]
    return conn


def _make_workspace(num: int = 1, leaves: list[Any] | None = None) -> MagicMock:
    """Create a mock workspace Con."""
    ws = MagicMock()
    ws.num = num
    ws.leaves.return_value = leaves if leaves is not None else []
    return ws


def _make_focused(workspace: MagicMock | None = None) -> MagicMock:
    """Create a mock focused container that belongs to a workspace."""
    focused = MagicMock()
    focused.workspace.return_value = workspace
    return focused


def _setup_tree(
    conn: MagicMock,
    focused: MagicMock | None = None,
    workspaces: list[MagicMock] | None = None,
) -> MagicMock:
    """Wire up conn.get_tree() to return a tree with find_focused and workspaces."""
    tree = MagicMock()
    tree.find_focused.return_value = focused
    tree.workspaces.return_value = workspaces or []
    conn.get_tree.return_value = tree
    return tree


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


class TestGetConnection:
    @patch("i3nator.workspace.Connection")
    def test_returns_connection(self, mock_conn_cls: MagicMock) -> None:
        sentinel = MagicMock()
        mock_conn_cls.return_value = sentinel
        assert get_connection() is sentinel

    @patch("i3nator.workspace.Connection", side_effect=Exception("socket error"))
    def test_raises_workspace_error_on_failure(self, mock_conn_cls: MagicMock) -> None:
        with pytest.raises(WorkspaceError, match="cannot connect to i3"):
            get_connection()

    @patch("i3nator.workspace.Connection", side_effect=OSError("no such socket"))
    def test_wraps_os_error(self, mock_conn_cls: MagicMock) -> None:
        with pytest.raises(WorkspaceError, match="cannot connect to i3"):
            get_connection()


# ---------------------------------------------------------------------------
# get_focused_workspace
# ---------------------------------------------------------------------------


class TestGetFocusedWorkspace:
    def test_returns_workspace_of_focused_window(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=3)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        result = get_focused_workspace(conn)
        assert result is ws

    def test_raises_when_no_focused_window(self) -> None:
        conn = _make_conn()
        _setup_tree(conn, focused=None)

        with pytest.raises(WorkspaceError, match="no focused window found"):
            get_focused_workspace(conn)

    def test_raises_when_focused_has_no_workspace(self) -> None:
        conn = _make_conn()
        focused = _make_focused(workspace=None)
        _setup_tree(conn, focused=focused)

        with pytest.raises(WorkspaceError, match="no parent workspace"):
            get_focused_workspace(conn)


# ---------------------------------------------------------------------------
# switch_to_workspace
# ---------------------------------------------------------------------------


class TestSwitchToWorkspace:
    def test_switch_by_number(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=5)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        switch_to_workspace(conn, number=5)
        conn.command.assert_any_call("workspace number 5")

    def test_no_switch_when_number_is_none(self) -> None:
        conn = _make_conn()
        switch_to_workspace(conn, number=None, name=None)
        conn.command.assert_not_called()

    def test_rename_with_number(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=5)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        switch_to_workspace(conn, number=5, name="calculus")

        calls = [c.args[0] for c in conn.command.call_args_list]
        assert "workspace number 5" in calls
        assert 'rename workspace to "5:calculus"' in calls

    def test_rename_without_number_uses_current(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=3)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        switch_to_workspace(conn, number=None, name="dev")

        calls = [c.args[0] for c in conn.command.call_args_list]
        # Should NOT switch workspace (number is None)
        assert not any("workspace number" in c for c in calls)
        # Should rename using current ws num
        assert 'rename workspace to "3:dev"' in calls

    def test_rename_when_ws_num_is_none(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=None)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        switch_to_workspace(conn, number=None, name="scratch")

        calls = [c.args[0] for c in conn.command.call_args_list]
        # When ws_num is None, name is used directly without prefix
        assert 'rename workspace to "scratch"' in calls

    def test_switch_and_rename(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=7)
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        switch_to_workspace(conn, number=7, name="music")

        calls = [c.args[0] for c in conn.command.call_args_list]
        assert calls[0] == "workspace number 7"
        assert calls[1] == 'rename workspace to "7:music"'


# ---------------------------------------------------------------------------
# workspace_is_empty
# ---------------------------------------------------------------------------


class TestWorkspaceIsEmpty:
    def test_empty_workspace_by_number(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=2, leaves=[])
        _setup_tree(conn, workspaces=[ws])

        assert workspace_is_empty(conn, number=2) is True

    def test_occupied_workspace_by_number(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=2, leaves=[leaf])
        _setup_tree(conn, workspaces=[ws])

        assert workspace_is_empty(conn, number=2) is False

    def test_nonexistent_workspace_is_empty(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=1, leaves=[])
        _setup_tree(conn, workspaces=[ws])

        # Workspace 99 doesn't exist — treated as empty
        assert workspace_is_empty(conn, number=99) is True

    def test_current_workspace_empty(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=1, leaves=[])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        assert workspace_is_empty(conn, number=None) is True

    def test_current_workspace_occupied(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=1, leaves=[leaf])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        assert workspace_is_empty(conn, number=None) is False

    def test_current_workspace_no_focused(self) -> None:
        conn = _make_conn()
        _setup_tree(conn, focused=None)

        # No focused window — treated as empty
        assert workspace_is_empty(conn, number=None) is True

    def test_current_workspace_focused_no_ws(self) -> None:
        conn = _make_conn()
        focused = _make_focused(workspace=None)
        _setup_tree(conn, focused=focused)

        # Focused has no workspace — treated as empty
        assert workspace_is_empty(conn, number=None) is True

    def test_multiple_workspaces_finds_correct_one(self) -> None:
        conn = _make_conn()
        ws1 = _make_workspace(num=1, leaves=[MagicMock()])
        ws2 = _make_workspace(num=2, leaves=[])
        ws3 = _make_workspace(num=3, leaves=[MagicMock(), MagicMock()])
        _setup_tree(conn, workspaces=[ws1, ws2, ws3])

        assert workspace_is_empty(conn, number=1) is False
        assert workspace_is_empty(conn, number=2) is True
        assert workspace_is_empty(conn, number=3) is False


# ---------------------------------------------------------------------------
# ensure_workspace_available
# ---------------------------------------------------------------------------


class TestEnsureWorkspaceAvailable:
    def test_force_always_passes(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=1, leaves=[leaf])
        _setup_tree(conn, workspaces=[ws])

        # Should not raise even though workspace is occupied
        ensure_workspace_available(conn, number=1, force=True)

    def test_empty_workspace_passes(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=2, leaves=[])
        _setup_tree(conn, workspaces=[ws])

        ensure_workspace_available(conn, number=2, force=False)

    def test_occupied_workspace_raises(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=3, leaves=[leaf])
        _setup_tree(conn, workspaces=[ws])

        with pytest.raises(WorkspaceOccupiedError, match="workspace 3 is not empty"):
            ensure_workspace_available(conn, number=3, force=False)

    def test_occupied_current_workspace_raises(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=1, leaves=[leaf])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        with pytest.raises(WorkspaceOccupiedError, match="current workspace is not empty"):
            ensure_workspace_available(conn, number=None, force=False)

    def test_error_message_includes_force_hint(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=5, leaves=[leaf])
        _setup_tree(conn, workspaces=[ws])

        with pytest.raises(WorkspaceOccupiedError, match="--force"):
            ensure_workspace_available(conn, number=5, force=False)

    def test_nonexistent_workspace_passes(self) -> None:
        conn = _make_conn()
        _setup_tree(conn, workspaces=[])

        ensure_workspace_available(conn, number=99, force=False)


# ---------------------------------------------------------------------------
# clear_workspace
# ---------------------------------------------------------------------------


class TestClearWorkspace:
    def test_kills_all_leaves(self) -> None:
        conn = _make_conn()
        leaf1 = MagicMock()
        leaf2 = MagicMock()
        leaf3 = MagicMock()
        ws = _make_workspace(num=1, leaves=[leaf1, leaf2, leaf3])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        clear_workspace(conn)

        leaf1.command.assert_called_once_with("kill")
        leaf2.command.assert_called_once_with("kill")
        leaf3.command.assert_called_once_with("kill")

    def test_empty_workspace_no_kills(self) -> None:
        conn = _make_conn()
        ws = _make_workspace(num=1, leaves=[])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        clear_workspace(conn)
        # No errors, no kill calls

    def test_no_focused_window(self) -> None:
        conn = _make_conn()
        _setup_tree(conn, focused=None)

        # Should return silently
        clear_workspace(conn)

    def test_focused_no_workspace(self) -> None:
        conn = _make_conn()
        focused = _make_focused(workspace=None)
        _setup_tree(conn, focused=focused)

        # Should return silently
        clear_workspace(conn)

    def test_single_leaf(self) -> None:
        conn = _make_conn()
        leaf = MagicMock()
        ws = _make_workspace(num=1, leaves=[leaf])
        focused = _make_focused(workspace=ws)
        _setup_tree(conn, focused=focused)

        clear_workspace(conn)

        leaf.command.assert_called_once_with("kill")
