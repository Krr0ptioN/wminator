"""YAML config loading, schema validation, and path expansion."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from i3nator.exceptions import ConfigNotFoundError, ValidationError

CONFIG_DIR = Path(os.environ.get("I3NATOR_CONFIG_DIR", "~/.config/i3nator")).expanduser()

VALID_LAYOUTS = {"splith", "splitv", "stacked", "tabbed"}
VALID_SPLITS = {"horizontal", "vertical"}
VALID_WINDOW_TYPES = {"terminal", "app"}


def config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def list_configs() -> list[str]:
    """Return sorted list of available layout config names (without .yml)."""
    d = config_dir()
    return sorted(p.stem for p in d.glob("*.yml") if p.is_file())


def config_path(name: str) -> Path:
    """Return the path to a named config file, raising if it doesn't exist."""
    p = config_dir() / f"{name}.yml"
    if not p.is_file():
        raise ConfigNotFoundError(f"layout config not found: {p}")
    return p


def load_config(name: str) -> dict[str, Any]:
    """Load and validate a named layout config."""
    p = config_path(name)
    with p.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValidationError(f"{p}: expected a YAML mapping, got {type(raw).__name__}")
    validate(raw, source=str(p))
    return raw


def load_config_from_path(path: str | Path) -> dict[str, Any]:
    """Load and validate a layout config from an arbitrary path."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ConfigNotFoundError(f"layout config not found: {p}")
    with p.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValidationError(f"{p}: expected a YAML mapping, got {type(raw).__name__}")
    validate(raw, source=str(p))
    return raw


def validate(cfg: dict[str, Any], source: str = "<config>") -> None:
    """Validate a parsed config dict against the expected schema."""
    if "name" not in cfg:
        raise ValidationError(f"{source}: missing required key 'name'")

    if "layout" not in cfg:
        raise ValidationError(f"{source}: missing required key 'layout'")

    if "workspace" in cfg and not isinstance(cfg["workspace"], int):
        raise ValidationError(f"{source}: 'workspace' must be an integer")

    if "terminal" in cfg and not isinstance(cfg["terminal"], str):
        raise ValidationError(f"{source}: 'terminal' must be a string")

    _validate_node(cfg["layout"], path="layout", source=source)


def _validate_node(node: Any, path: str, source: str) -> None:
    """Recursively validate a layout tree node."""
    if not isinstance(node, dict):
        raise ValidationError(f"{source}: {path}: expected a mapping")

    # Must have either 'split'/'layout' (container) or 'command' (window), but not both via
    # the presence of 'children'.
    has_children = "children" in node
    has_command = "command" in node

    if has_children and has_command:
        raise ValidationError(f"{source}: {path}: node cannot have both 'command' and 'children'")

    if has_children:
        _validate_container(node, path, source)
    elif has_command:
        _validate_window(node, path, source)
    else:
        # Root layout node: must have 'split' and 'children'
        if "split" in node:
            if node["split"] not in VALID_SPLITS:
                raise ValidationError(f"{source}: {path}.split: must be one of {VALID_SPLITS}")
            if "children" not in node:
                raise ValidationError(f"{source}: {path}: 'split' container must have 'children'")
        elif "layout" in node and isinstance(node["layout"], str):
            # container with layout but no children yet — still needs children
            raise ValidationError(f"{source}: {path}: container must have 'children'")
        else:
            raise ValidationError(
                f"{source}: {path}: node must have 'command' (window) or 'children' (container)"
            )


def _validate_container(node: dict, path: str, source: str) -> None:
    """Validate a container node with children."""
    children = node["children"]
    if not isinstance(children, list) or len(children) == 0:
        raise ValidationError(f"{source}: {path}.children: must be a non-empty list")

    if "split" in node and node["split"] not in VALID_SPLITS:
        raise ValidationError(f"{source}: {path}.split: must be one of {VALID_SPLITS}")

    if (
        "layout" in node
        and isinstance(node["layout"], str)
        and node["layout"] not in VALID_LAYOUTS
    ):
        raise ValidationError(f"{source}: {path}.layout: must be one of {VALID_LAYOUTS}")

    for i, child in enumerate(children):
        if not isinstance(child, dict):
            raise ValidationError(f"{source}: {path}.children[{i}]: expected a mapping")

        # Each child is either {"window": {...}} or {"container": {...}}
        if "window" in child:
            _validate_window(child["window"], f"{path}.children[{i}].window", source)
        elif "container" in child:
            _validate_node(child["container"], f"{path}.children[{i}].container", source)
        else:
            raise ValidationError(
                f"{source}: {path}.children[{i}]: must have 'window' or 'container' key"
            )


def _validate_window(node: dict, path: str, source: str) -> None:
    """Validate a window leaf node."""
    if "command" not in node:
        raise ValidationError(f"{source}: {path}: window must have 'command'")

    wtype = node.get("type", "terminal")
    if wtype not in VALID_WINDOW_TYPES:
        raise ValidationError(f"{source}: {path}.type: must be one of {VALID_WINDOW_TYPES}")

    if "ratio" in node:
        r = node["ratio"]
        if not isinstance(r, int | float) or r <= 0 or r > 100:
            raise ValidationError(f"{source}: {path}.ratio: must be a number between 0 and 100")

    if "match" in node:
        match = node["match"]
        if not isinstance(match, dict):
            raise ValidationError(f"{source}: {path}.match: must be a mapping")
        for key in match:
            if key not in ("class", "title", "instance"):
                raise ValidationError(
                    f"{source}: {path}.match.{key}: unknown match key "
                    f"(expected 'class', 'title', or 'instance')"
                )


def expand_command(command: str) -> str:
    """Expand ~ and environment variables in a command string."""
    return os.path.expandvars(os.path.expanduser(command))
