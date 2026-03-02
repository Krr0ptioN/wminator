"""Tests for i3nator.config — loading, validation, and path expansion."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from i3nator.config import (
    VALID_LAYOUTS,
    VALID_SPLITS,
    VALID_WINDOW_TYPES,
    config_path,
    expand_command,
    list_configs,
    load_config,
    load_config_from_path,
    validate,
)
from i3nator.exceptions import ConfigNotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override CONFIG_DIR to a temp directory for testing."""
    import i3nator.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    return tmp_path


def _minimal_config(**overrides: object) -> dict:
    """Return the smallest valid config dict, with optional overrides."""
    cfg: dict = {
        "name": "test",
        "layout": {
            "split": "horizontal",
            "children": [
                {"window": {"command": "echo hello", "type": "terminal"}},
            ],
        },
    }
    cfg.update(overrides)
    return cfg


def _write_yaml(path: Path, data: dict) -> Path:
    with path.open("w") as f:
        yaml.safe_dump(data, f)
    return path


# ---------------------------------------------------------------------------
# list_configs
# ---------------------------------------------------------------------------


class TestListConfigs:
    def test_empty_dir(self, config_dir: Path) -> None:
        assert list_configs() == []

    def test_returns_sorted_stems(self, config_dir: Path) -> None:
        _write_yaml(config_dir / "bravo.yml", _minimal_config(name="bravo"))
        _write_yaml(config_dir / "alpha.yml", _minimal_config(name="alpha"))
        (config_dir / "not-yaml.txt").write_text("ignored")
        assert list_configs() == ["alpha", "bravo"]

    def test_ignores_directories(self, config_dir: Path) -> None:
        (config_dir / "subdir.yml").mkdir()
        assert list_configs() == []


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


class TestConfigPath:
    def test_existing_config(self, config_dir: Path) -> None:
        expected = config_dir / "dev.yml"
        _write_yaml(expected, _minimal_config(name="dev"))
        assert config_path("dev") == expected

    def test_missing_raises(self, config_dir: Path) -> None:
        with pytest.raises(ConfigNotFoundError, match="no-such"):
            config_path("no-such")


# ---------------------------------------------------------------------------
# load_config / load_config_from_path
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_load_by_name(self, config_dir: Path) -> None:
        data = _minimal_config(name="foo")
        _write_yaml(config_dir / "foo.yml", data)
        loaded = load_config("foo")
        assert loaded["name"] == "foo"
        assert "layout" in loaded

    def test_load_by_path(self, tmp_path: Path) -> None:
        p = tmp_path / "custom.yml"
        _write_yaml(p, _minimal_config(name="custom"))
        loaded = load_config_from_path(p)
        assert loaded["name"] == "custom"

    def test_load_nonexistent_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigNotFoundError):
            load_config_from_path(tmp_path / "ghost.yml")

    def test_load_non_mapping_raises(self, config_dir: Path) -> None:
        p = config_dir / "bad.yml"
        p.write_text("- just a list\n")
        with pytest.raises(ValidationError, match="expected a YAML mapping"):
            load_config("bad")


# ---------------------------------------------------------------------------
# validate — top-level keys
# ---------------------------------------------------------------------------


class TestValidateTopLevel:
    def test_minimal_valid(self) -> None:
        validate(_minimal_config())

    def test_missing_name_raises(self) -> None:
        cfg = _minimal_config()
        del cfg["name"]
        with pytest.raises(ValidationError, match="missing required key 'name'"):
            validate(cfg)

    def test_missing_layout_raises(self) -> None:
        cfg = _minimal_config()
        del cfg["layout"]
        with pytest.raises(ValidationError, match="missing required key 'layout'"):
            validate(cfg)

    def test_workspace_must_be_int(self) -> None:
        with pytest.raises(ValidationError, match="'workspace' must be an integer"):
            validate(_minimal_config(workspace="five"))

    def test_workspace_int_ok(self) -> None:
        validate(_minimal_config(workspace=5))

    def test_terminal_must_be_string(self) -> None:
        with pytest.raises(ValidationError, match="'terminal' must be a string"):
            validate(_minimal_config(terminal=42))

    def test_terminal_string_ok(self) -> None:
        validate(_minimal_config(terminal="alacritty"))


# ---------------------------------------------------------------------------
# validate — layout nodes
# ---------------------------------------------------------------------------


class TestValidateLayoutNodes:
    def test_valid_splits(self) -> None:
        for split in VALID_SPLITS:
            cfg = _minimal_config()
            cfg["layout"]["split"] = split
            validate(cfg)  # should not raise

    def test_invalid_split_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["split"] = "diagonal"
        with pytest.raises(ValidationError, match="split"):
            validate(cfg)

    def test_valid_container_layouts(self) -> None:
        for layout in VALID_LAYOUTS:
            cfg = _minimal_config()
            cfg["layout"] = {
                "split": "horizontal",
                "children": [
                    {
                        "container": {
                            "layout": layout,
                            "children": [
                                {"window": {"command": "echo hi", "type": "terminal"}},
                            ],
                        }
                    },
                ],
            }
            validate(cfg)

    def test_invalid_container_layout_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"] = {
            "split": "horizontal",
            "children": [
                {
                    "container": {
                        "layout": "floating",
                        "children": [
                            {"window": {"command": "echo hi"}},
                        ],
                    }
                },
            ],
        }
        with pytest.raises(ValidationError, match="layout"):
            validate(cfg)

    def test_node_with_command_and_children_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"] = {
            "command": "echo conflict",
            "children": [{"window": {"command": "echo hi"}}],
        }
        with pytest.raises(ValidationError, match="cannot have both 'command' and 'children'"):
            validate(cfg)

    def test_empty_children_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"] = {"split": "horizontal", "children": []}
        with pytest.raises(ValidationError, match="non-empty list"):
            validate(cfg)

    def test_child_without_window_or_container_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"] = {
            "split": "horizontal",
            "children": [{"unknown_key": {}}],
        }
        with pytest.raises(ValidationError, match="must have 'window' or 'container'"):
            validate(cfg)


# ---------------------------------------------------------------------------
# validate — window nodes
# ---------------------------------------------------------------------------


class TestValidateWindows:
    def test_window_missing_command_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [{"window": {"type": "terminal"}}]
        with pytest.raises(ValidationError, match="window must have 'command'"):
            validate(cfg)

    def test_valid_window_types(self) -> None:
        for wtype in VALID_WINDOW_TYPES:
            cfg = _minimal_config()
            cfg["layout"]["children"] = [
                {"window": {"command": "echo test", "type": wtype}},
            ]
            validate(cfg)

    def test_invalid_window_type_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [
            {"window": {"command": "echo test", "type": "daemon"}},
        ]
        with pytest.raises(ValidationError, match="type"):
            validate(cfg)

    def test_ratio_must_be_number(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [
            {"window": {"command": "echo test", "ratio": "half"}},
        ]
        with pytest.raises(ValidationError, match="ratio"):
            validate(cfg)

    def test_ratio_bounds(self) -> None:
        for bad_ratio in [0, -5, 101]:
            cfg = _minimal_config()
            cfg["layout"]["children"] = [
                {"window": {"command": "echo test", "ratio": bad_ratio}},
            ]
            with pytest.raises(ValidationError, match="ratio"):
                validate(cfg)

    def test_ratio_valid_values(self) -> None:
        for good_ratio in [1, 50, 99.5, 100]:
            cfg = _minimal_config()
            cfg["layout"]["children"] = [
                {"window": {"command": "echo test", "ratio": good_ratio}},
            ]
            validate(cfg)  # should not raise

    def test_match_must_be_dict(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [
            {"window": {"command": "echo test", "match": "Zathura"}},
        ]
        with pytest.raises(ValidationError, match="match: must be a mapping"):
            validate(cfg)

    def test_match_unknown_key_raises(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [
            {"window": {"command": "echo test", "match": {"pid": "123"}}},
        ]
        with pytest.raises(ValidationError, match="unknown match key"):
            validate(cfg)

    def test_match_valid_keys(self) -> None:
        cfg = _minimal_config()
        cfg["layout"]["children"] = [
            {
                "window": {
                    "command": "echo test",
                    "match": {"class": "Firefox", "title": "home", "instance": "nav"},
                }
            },
        ]
        validate(cfg)  # should not raise


# ---------------------------------------------------------------------------
# validate — nested layout (matches examples/calculus.yml structure)
# ---------------------------------------------------------------------------


class TestValidateNested:
    def test_calculus_style_config(self) -> None:
        """Validates a config matching the calculus.yml example."""
        cfg = {
            "name": "calculus",
            "workspace": 5,
            "workspace_name": "calculus",
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
                                        "command": "zathura '~/rsc/textbook.pdf'",
                                        "type": "app",
                                        "match": {"class": "Zathura"},
                                    }
                                },
                                {
                                    "window": {
                                        "command": "zathura '~/homework.pdf'",
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
        validate(cfg)  # should not raise


# ---------------------------------------------------------------------------
# expand_command
# ---------------------------------------------------------------------------


class TestExpandCommand:
    def test_tilde_expansion(self) -> None:
        result = expand_command("~/file.txt")
        assert result.startswith("/")
        assert "~" not in result

    def test_env_var_expansion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("I3N_TEST_VAR", "/opt/bin")
        result = expand_command("$I3N_TEST_VAR/run")
        assert result == "/opt/bin/run"

    def test_combined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("I3N_APP", "firefox")
        result = expand_command("~/$I3N_APP")
        home = os.path.expanduser("~")
        assert result == f"{home}/firefox"

    def test_no_expansion_needed(self) -> None:
        assert expand_command("echo hello") == "echo hello"
