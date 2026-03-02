"""Recursive i3 layout engine — the core of i3nator.

Walks the YAML layout tree depth-first, issuing i3 split/layout/resize
commands and spawning windows via the launcher module.

Algorithm for each container:
  1. Spawn the first child (creates a leaf node in i3).
  2. Before each subsequent child, issue ``split h|v`` on the focused
     container so i3 creates a new frame in the right direction.
  3. After all children are placed, if the container has a special layout
     (stacked/tabbed), walk up with ``focus parent`` and set it.
  4. Apply size ratios via resize commands.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from i3ipc import Connection

from i3nator.exceptions import LayoutError
from i3nator.launcher import spawn_window

log = logging.getLogger(__name__)

# Brief pause between i3 commands to let the tree settle.
_CMD_DELAY = 0.05


def apply_layout(conn: Connection, config: dict[str, Any]) -> None:
    """Apply a full layout config to the current workspace.

    This is the main entry point called by the CLI after workspace
    preparation is complete.
    """
    terminal = config.get("terminal", "wezterm")
    root = config["layout"]

    log.info("applying layout %r", config.get("name", "<unnamed>"))
    _apply_container(conn, root, terminal=terminal, depth=0)
    log.info("layout applied successfully")


def _apply_container(
    conn: Connection,
    node: dict[str, Any],
    terminal: str,
    depth: int,
) -> None:
    """Recursively apply a container node.

    A container has ``children`` (a list of ``window`` or ``container``
    dicts) and optionally a ``split`` direction and/or a ``layout``
    (stacked/tabbed/splitv/splith).
    """
    children = node.get("children", [])
    if not children:
        raise LayoutError("container has no children")

    split_dir = _split_direction(node)
    container_layout = node.get("layout")  # stacked | tabbed | splitv | splith

    # ------------------------------------------------------------------
    # Phase 1: place every child window / recurse into sub-containers
    # ------------------------------------------------------------------
    for idx, child in enumerate(children):
        # Before every child *after* the first, tell i3 which direction
        # to split so the new window lands in the right place.
        if idx > 0:
            _cmd(conn, f"split {split_dir}")

        if "window" in child:
            _place_window(conn, child["window"], terminal=terminal, depth=depth)
        elif "container" in child:
            _apply_container(conn, child["container"], terminal=terminal, depth=depth + 1)
        else:
            raise LayoutError(f"child at index {idx} has neither 'window' nor 'container'")

    # ------------------------------------------------------------------
    # Phase 2: set container layout (stacked / tabbed) if requested
    # ------------------------------------------------------------------
    if container_layout in ("stacked", "tabbed", "splitv", "splith"):
        _set_container_layout(conn, container_layout, child_count=len(children))

    # ------------------------------------------------------------------
    # Phase 3: apply ratios (resize children to requested proportions)
    # ------------------------------------------------------------------
    ratios = _collect_ratios(children)
    if ratios:
        _apply_ratios(conn, children, ratios, split_dir)


def _place_window(
    conn: Connection,
    window: dict[str, Any],
    terminal: str,
    depth: int,
) -> None:
    """Spawn a single window and wait for it to appear."""
    command = window["command"]
    wtype = window.get("type", "terminal")
    match = window.get("match")
    timeout = window.get("timeout", 10.0)

    log.debug("placing window: %s (type=%s, match=%s)", command, wtype, match)

    spawn_window(
        conn,
        command=command,
        window_type=wtype,
        terminal=terminal,
        match=match,
        timeout=timeout,
    )

    # Small delay to let i3 finish any internal tree rearrangement.
    time.sleep(_CMD_DELAY)


def _split_direction(node: dict[str, Any]) -> str:
    """Determine the split direction character for i3 commands.

    Returns ``"h"`` (horizontal) or ``"v"`` (vertical).

    The YAML uses human-friendly names:
      - ``split: horizontal`` → windows side by side → i3 ``split h``
      - ``split: vertical``   → windows stacked top/bottom → i3 ``split v``

    For containers that declare a ``layout`` instead of ``split``:
      - ``splith`` → ``"h"``
      - ``splitv`` / ``stacked`` / ``tabbed`` → ``"v"``

    Defaults to horizontal if unspecified.
    """
    explicit = node.get("split")
    if explicit == "horizontal":
        return "h"
    if explicit == "vertical":
        return "v"

    layout = node.get("layout")
    if layout == "splith":
        return "h"
    if layout in ("splitv", "stacked", "tabbed"):
        return "v"

    return "h"


def _set_container_layout(
    conn: Connection,
    layout: str,
    child_count: int,
) -> None:
    """Focus the parent container and set its layout.

    After placing all children the focus is on the last child (a leaf).
    We need to walk up to the parent container that holds all the children
    and set its layout.
    """
    # Walk up from the last child to the enclosing container.
    _cmd(conn, "focus parent")
    _cmd(conn, f"layout {layout}")

    # Return focus to the first child so subsequent operations work from
    # a predictable position.  Move to the first child via ``focus child``.
    _cmd(conn, "focus child")


def _collect_ratios(children: list[dict[str, Any]]) -> list[float | None]:
    """Extract ratio values from children, returning None if none are set."""
    ratios: list[float | None] = []
    any_set = False
    for child in children:
        inner = child.get("window") or child.get("container") or {}
        r = inner.get("ratio")
        ratios.append(r)
        if r is not None:
            any_set = True
    return ratios if any_set else []


def _apply_ratios(
    conn: Connection,
    children: list[dict[str, Any]],
    ratios: list[float | None],
    split_dir: str,
) -> None:
    """Resize children to match the requested ratio proportions.

    Strategy: iterate children from last to first, resizing each one
    relative to the remaining space.  This avoids cumulative rounding
    errors that would occur going left-to-right.

    The resize is done in the axis perpendicular to the split direction
    (i3's ``resize set`` uses width/height of the container).
    """
    n = len(children)
    if n < 2:
        return

    # Fill in missing ratios with equal shares of remaining space.
    total_explicit = sum(r for r in ratios if r is not None)
    count_missing = sum(1 for r in ratios if r is None)
    if count_missing > 0:
        remaining = max(100.0 - total_explicit, 0.0)
        default = remaining / count_missing if count_missing else 0.0
        ratios = [r if r is not None else default for r in ratios]

    # Normalize so they sum to 100.
    total = sum(r for r in ratios if r is not None)
    if total and total != 100:
        ratios = [(r / total * 100) if r is not None else None for r in ratios]

    axis = "width" if split_dir == "h" else "height"

    # Focus the parent container first so we can navigate between children.
    _cmd(conn, "focus parent")
    _cmd(conn, "focus child")  # focus first child

    for i in range(n):
        ppt = ratios[i]
        if ppt is not None:
            ppt_int = round(ppt)
            if ppt_int > 0:
                _cmd(conn, f"resize set {axis} {ppt_int} ppt")

        # Move to next sibling.
        if i < n - 1:
            next_dir = "right" if split_dir == "h" else "down"
            _cmd(conn, f"focus {next_dir}")


def _cmd(conn: Connection, command: str) -> None:
    """Send a command to i3 and log it."""
    log.debug("i3 command: %s", command)
    replies = conn.command(command)
    for reply in replies:
        if not reply.success:  # type: ignore[attr-defined]
            log.warning("i3 command failed: %s → %s", command, reply.error)  # type: ignore[attr-defined]
    time.sleep(_CMD_DELAY)
