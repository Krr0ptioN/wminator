"""Rofi integration: list layouts for selection and open the chosen one."""

from __future__ import annotations

import subprocess

from i3nator.config import list_configs


def rofi_select(prompt: str = "i3nator:", theme: str = "vercel-premium") -> str | None:
    """Show a rofi dmenu with available layout configs and return the selection.

    Returns the selected layout name, or None if the user cancelled.
    """
    configs = list_configs()
    if not configs:
        return None

    input_text = "\n".join(configs)
    argv = ["rofi", "-dmenu", "-i", "-p", prompt, "-theme", theme]

    try:
        result = subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    selection = result.stdout.strip()
    if result.returncode != 0 or not selection:
        return None

    return selection


def format_config_list(configs: list[str]) -> str:
    """Format a list of config names for terminal display."""
    if not configs:
        return "No layouts found."
    return "\n".join(configs)
