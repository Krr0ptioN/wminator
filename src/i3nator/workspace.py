"""i3 workspace operations: switch, rename, check occupancy, and clear."""

from __future__ import annotations

from typing import Any

from i3ipc import Connection

from i3nator.exceptions import WorkspaceError, WorkspaceOccupiedError


def get_connection() -> Connection:
    """Return an i3ipc connection, raising WorkspaceError on failure."""
    try:
        return Connection()
    except Exception as exc:
        raise WorkspaceError(f"cannot connect to i3: {exc}") from exc


def get_focused_workspace(conn: Connection) -> Any:
    """Return the currently focused workspace (i3ipc Con)."""
    tree = conn.get_tree()
    focused = tree.find_focused()
    if focused is None:
        raise WorkspaceError("no focused window found")
    ws = focused.workspace()
    if ws is None:
        raise WorkspaceError("focused window has no parent workspace")
    return ws


def switch_to_workspace(
    conn: Connection, number: int | None = None, name: str | None = None
) -> None:
    """Switch to a workspace by number, optionally renaming it.

    If number is None, stays on the current workspace.
    If name is provided, the workspace is renamed to "<number>:<name>".
    """
    if number is not None:
        conn.command(f"workspace number {number}")

    if name is not None:
        ws = get_focused_workspace(conn)
        ws_num = ws.num
        new_name = f"{ws_num}:{name}" if ws_num is not None else name
        conn.command(f'rename workspace to "{new_name}"')


def workspace_is_empty(conn: Connection, number: int | None = None) -> bool:
    """Check whether a workspace has no windows.

    If number is None, checks the currently focused workspace.
    """
    tree = conn.get_tree()

    if number is not None:
        workspaces = [ws for ws in tree.workspaces() if ws.num == number]  # type: ignore[attr-defined]
        if not workspaces:
            # Workspace doesn't exist yet — it's empty.
            return True
        ws = workspaces[0]
    else:
        focused = tree.find_focused()
        if focused is None:
            return True
        ws = focused.workspace()

    if ws is None:
        return True
    return len(ws.leaves()) == 0  # type: ignore[attr-defined]


def ensure_workspace_available(
    conn: Connection, number: int | None = None, force: bool = False
) -> None:
    """Raise WorkspaceOccupiedError if the target workspace has windows and force is False."""
    if force:
        return

    if not workspace_is_empty(conn, number):
        target = f"workspace {number}" if number is not None else "current workspace"
        raise WorkspaceOccupiedError(f"{target} is not empty (use --force to override)")


def clear_workspace(conn: Connection) -> None:
    """Kill all windows on the currently focused workspace."""
    tree = conn.get_tree()
    focused = tree.find_focused()
    if focused is None:
        return
    ws = focused.workspace()
    if ws is None:
        return
    for leaf in ws.leaves():  # type: ignore[attr-defined]
        leaf.command("kill")
