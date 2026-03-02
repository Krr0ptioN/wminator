# i3nator

Declarative i3 workspace layout manager — tmuxinator for i3.

Define your i3 workspace layouts in YAML and launch them with a single command.

## Installation

```bash
make dev
```

## Usage

```bash
# List available workspace layouts
i3nator list

# Open a workspace layout
i3nator open calculus

# Open without prompt if workspace has existing windows
i3nator open calculus --force

# Create a new layout from template
i3nator create my-project

# Edit a layout in $EDITOR
i3nator edit calculus

# Validate a layout file
i3nator validate calculus

# Output list for rofi integration
i3nator rofi
```

## Configuration

Workspace layouts are stored as YAML files in `~/.config/i3nator/`.

### Example: Calculus Studies

```yaml
name: calculus
workspace: 5
workspace_name: "calculus"
terminal: wezterm

layout:
  split: horizontal
  children:
    - window:
        command: "tmuxinator start acu"
        type: terminal
        ratio: 50

    - container:
        layout: stacked
        ratio: 50
        children:
          - window:
              command: "zathura '~/rsc/calculus-textbook.pdf'"
              type: app
              match:
                class: Zathura

          - window:
              command: "zathura '~/homework.pdf'"
              type: app
              match:
                class: Zathura
                title: "homework"
```

### Layout Options

- `split`: `horizontal` or `vertical` — the split direction of the container
- `layout`: `stacked`, `tabbed`, `splitv`, `splith` — the i3 container layout
- `type`: `terminal` (wrapped in terminal emulator) or `app` (launched directly)
- `match`: window matching criteria (`class`, `title` — used to detect the window after launch)
- `ratio`: percentage of parent container width/height

## Rofi Integration

Use the included `scripts/rofi-i3nator` script with your hotkey daemon:

```
super + shift + o
    ~/.script/rofi-i3nator
```

## License

MIT
