# wminator

Declarative workspace layout manager for i3 and Sway — tmuxinator for tiling window managers.

`wminator` reads typed YAML layouts, prepares a workspace, launches each window sequentially, and recreates nested splits, container layouts, and ratios. It uses asynchronous i3-compatible IPC and detects newly created windows without killing applications on timeout.

## Install

Linux and Rust 1.85 or newer are required.

```bash
cargo install --locked --path .
```

Tagged releases provide GNU and musl archives for x86-64 and AArch64. Each archive contains `wminator`, `rofi-wminator`, this README, and the license.

## Usage

```bash
wminator list
wminator open calculus
wminator open calculus --force
wminator create my-project
wminator edit calculus
wminator validate calculus
wminator rofi
wminator --backend sway open calculus
```

The backend is selected by an explicit `--backend i3|sway`, then a non-empty `SWAYSOCK`, then `I3SOCK` classified via the compositor version response. If no socket is available, wminator explains how to override selection.

## Configuration

Layouts are named `*.yml` files in `${WMINATOR_CONFIG_DIR}` or `~/.config/wminator`. `open` and `validate` also accept explicit `.yml`/`.yaml` paths. Unknown fields and invalid values are rejected with a file and field path.

```yaml
name: calculus
workspace: 5
workspace_name: calculus
terminal: wezterm

layout:
  split: horizontal
  children:
    - window:
        command: tmuxinator start calculus
        type: terminal
        ratio: 50
    - container:
        layout: stacked
        ratio: 50
        children:
          - window:
              command: zathura ~/rsc/calculus-textbook.pdf
              type: app
              match:
                class: Zathura
          - window:
              command: foot
              type: app
              match:
                app_id: foot
```

Containers support `split: horizontal|vertical` and `layout: splith|splitv|stacked|tabbed`. Windows support `type: terminal|app`, positive finite `timeout`, ratios from 0–100 (exclusive of zero), and case-insensitive substring matching on `class`, `title`, `instance`, and `app_id`. All supplied criteria must match. `app_id` is Sway-only; Sway's `class` checks XWayland class with `app_id` fallback.

Terminal conventions are built in for WezTerm, Alacritty, Kitty, st, and xterm. Other terminal names use `-e sh -c`. App commands use shell-word parsing, and commands expand environment variables and a leading tilde.

## Rofi

The built-in `wminator rofi` command supports `--prompt`, `--theme`, and `--force`. The standalone [`scripts/rofi-wminator`](scripts/rofi-wminator) script is suitable for a hotkey binding.

## Development

`make check` runs formatting, strict Clippy (including production unwrap/expect and unsafe bans), and all tests. Ignored live IPC smoke tests are selected with `WMINATOR_LIVE_BACKEND=i3|sway`.

## License

MIT
