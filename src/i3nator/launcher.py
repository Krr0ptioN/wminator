"""Window spawning and i3ipc event-based detection."""

from __future__ import annotations

import shlex
import subprocess
import time
from typing import Any

from i3ipc import Connection, Event

from i3nator.config import expand_command
from i3nator.exceptions import LaunchError, LaunchTimeoutError

DEFAULT_TIMEOUT = 10.0
POLL_INTERVAL = 0.05


def build_terminal_command(terminal: str, command: str) -> list[str]:
    """Build the argv for launching a command inside a terminal emulator."""
    cmd = expand_command(command)
    term = terminal.lower()

    if term in ("wezterm", "wezterm-gui"):
        return ["wezterm", "start", "--", "sh", "-c", cmd]
    if term in ("alacritty",):
        return ["alacritty", "-e", "sh", "-c", cmd]
    if term in ("kitty",):
        return ["kitty", "sh", "-c", cmd]
    if term in ("st", "suckless"):
        return ["st", "-e", "sh", "-c", cmd]

    if term in ("xterm",):
        return ["xterm", "-e", cmd]

    return [terminal, "-e", "sh", "-c", cmd]


def build_app_command(command: str) -> list[str]:
    """Build the argv for launching a standalone application."""
    return shlex.split(expand_command(command))


def spawn_window(
    conn: Connection,
    command: str,
    window_type: str = "terminal",
    terminal: str = "wezterm",
    match: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Spawn a window and wait for it to appear using i3ipc events.

    Returns the i3ipc container (Con) of the new window.
    """
    if window_type == "terminal":
        argv = build_terminal_command(terminal, command)
    elif window_type == "app":
        argv = build_app_command(command)
    else:
        raise LaunchError(f"unknown window type: {window_type}")

    result_container: list = []  # mutable container for closure

    def _on_window_new(_conn: Any, event: Any) -> None:
        """Callback for window::new events."""
        con = event.container
        if _matches(con, match):
            result_container.append(con)

    # Subscribe to window::new before spawning so we don't miss the event.
    conn.on(Event.WINDOW_NEW, _on_window_new)

    try:
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        conn.off(_on_window_new)
        raise LaunchError(f"command not found: {argv[0]}") from exc
    except OSError as exc:
        conn.off(_on_window_new)
        raise LaunchError(f"failed to spawn: {exc}") from exc

    # Poll for the window to appear.
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            # Check event-captured results first.
            if result_container:
                return result_container[0]

            # Process any pending i3ipc events (non-blocking).
            conn.main(timeout=POLL_INTERVAL)

            # Fallback: scan the tree directly in case the event was missed.
            container = _find_in_tree(conn, match)
            if container is not None:
                return container
    finally:
        conn.off(_on_window_new)

    # Check one last time before giving up.
    container = _find_in_tree(conn, match)
    if container is not None:
        return container

    raise LaunchTimeoutError(f"window did not appear within {timeout}s: {' '.join(argv)}")


def _matches(con: Any, match: dict[str, str] | None) -> bool:
    """Check whether an i3 container matches the given criteria.

    If match is None (terminal with no specific match criteria), any new window
    is considered a match — the caller is responsible for spawning only one
    window at a time.
    """
    if match is None:
        return True

    wm_class = getattr(con, "window_class", None) or ""
    title = getattr(con, "name", None) or ""
    instance = getattr(con, "window_instance", None) or ""

    for key, pattern in match.items():
        if key == "class" and pattern.lower() not in wm_class.lower():
            return False
        if key == "title" and pattern.lower() not in title.lower():
            return False
        if key == "instance" and pattern.lower() not in instance.lower():
            return False

    return True


def _find_in_tree(conn: Connection, match: dict[str, str] | None) -> Any | None:
    """Scan the i3 tree for a window matching the criteria.

    Returns the first matching leaf on the focused workspace, or None.
    """
    if match is None:
        return None  # Can't tree-scan without match criteria.

    tree = conn.get_tree()
    focused = tree.find_focused()
    if focused is None:
        return None

    ws = focused.workspace()
    if ws is None:
        return None
    for leaf in ws.leaves():
        if _matches(leaf, match):
            return leaf

    return None
