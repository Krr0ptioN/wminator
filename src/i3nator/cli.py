"""Click CLI for i3nator — declarative i3 workspace layout manager."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

import click

from i3nator import __version__
from i3nator.config import (
    config_dir,
    list_configs,
    load_config,
    load_config_from_path,
)
from i3nator.exceptions import (
    ConfigNotFoundError,
    I3natorError,
    ValidationError,
    WorkspaceOccupiedError,
)
from i3nator.layout import apply_layout
from i3nator.rofi import format_config_list, rofi_select
from i3nator.workspace import (
    ensure_workspace_available,
    get_connection,
    switch_to_workspace,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(name)s: %(message)s",
        level=level,
        stream=sys.stderr,
    )


@click.group()
@click.version_option(version=__version__, prog_name="i3nator")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """i3nator — declarative i3 workspace layout manager."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


# -- open ------------------------------------------------------------------


@main.command()
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip workspace occupancy check.")
@click.pass_context
def open(ctx: click.Context, name: str, force: bool) -> None:
    """Open a layout by name.

    NAME is the layout config name (without .yml extension), or a path
    ending in .yml to load from an arbitrary file.
    """
    try:
        if name.endswith(".yml") or name.endswith(".yaml") or os.sep in name:
            cfg = load_config_from_path(name)
        else:
            cfg = load_config(name)
    except I3natorError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        conn = get_connection()
    except I3natorError as exc:
        raise click.ClickException(str(exc)) from exc

    ws_number = cfg.get("workspace")
    ws_name = cfg.get("workspace_name")

    try:
        ensure_workspace_available(conn, ws_number, force=force)
    except WorkspaceOccupiedError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        switch_to_workspace(conn, number=ws_number, name=ws_name)
        apply_layout(conn, cfg)
    except I3natorError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"layout '{cfg.get('name', name)}' applied")


# -- list ------------------------------------------------------------------


@main.command("list")
def list_cmd() -> None:
    """List available layout configs."""
    configs = list_configs()
    click.echo(format_config_list(configs))


# -- edit ------------------------------------------------------------------


@main.command()
@click.argument("name")
def edit(name: str) -> None:
    """Edit a layout config in $EDITOR.

    Creates the config file if it doesn't exist.
    """
    path = config_dir() / f"{name}.yml"

    if not path.exists():
        path.write_text(_template(name))
        click.echo(f"created {path}")

    editor = os.environ.get("EDITOR", "vim")
    try:
        subprocess.run([editor, str(path)], check=True)
    except FileNotFoundError as err:
        raise click.ClickException(f"editor not found: {editor}") from err
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"editor exited with code {exc.returncode}") from exc


# -- create ----------------------------------------------------------------


@main.command()
@click.argument("name")
def create(name: str) -> None:
    """Create a new layout config from a template."""
    path = config_dir() / f"{name}.yml"

    if path.exists():
        raise click.ClickException(f"layout '{name}' already exists: {path}")

    path.write_text(_template(name))
    click.echo(f"created {path}")


# -- validate --------------------------------------------------------------


@main.command()
@click.argument("name")
def validate_cmd(name: str) -> None:
    """Validate a layout config.

    NAME is the layout name or a path to a .yml file.
    """
    try:
        if name.endswith(".yml") or name.endswith(".yaml") or os.sep in name:
            load_config_from_path(name)
        else:
            load_config(name)
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    except ConfigNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"'{name}' is valid")


# Register with the correct command name so `i3nator validate` works.
validate_cmd.name = "validate"


# -- rofi ------------------------------------------------------------------


@main.command()
@click.option("--prompt", default="i3nator:", help="Rofi prompt text.")
@click.option("--theme", default="vercel-premium", help="Rofi theme.")
@click.option("--force", "-f", is_flag=True, help="Skip workspace occupancy check.")
@click.pass_context
def rofi(ctx: click.Context, prompt: str, theme: str, force: bool) -> None:
    """Launch rofi to select and open a layout."""
    selection = rofi_select(prompt=prompt, theme=theme)
    if selection is None:
        return

    # Delegate to the open command.
    ctx.invoke(open, name=selection, force=force)


# -- helpers ---------------------------------------------------------------


def _template(name: str) -> str:
    """Return a starter YAML template for a new layout config."""
    return f"""\
name: {name}
# workspace: 3          # optional: target workspace number
# workspace_name: ""    # optional: rename workspace
terminal: wezterm        # terminal emulator to use

layout:
  split: horizontal
  children:
    - window:
        command: ""
        type: terminal
        ratio: 50
    - window:
        command: ""
        type: terminal
        ratio: 50
"""
