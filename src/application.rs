use async_recursion::async_recursion;
use std::{
    env,
    path::{Path, PathBuf},
    time::Duration,
};

use crate::{
    domain::{Axis, Backend, Container, ContainerLayout, LayoutConfig, Window, WindowType},
    error::{Result, WminatorError},
    ports::{ConfigRepository, Editor, MenuSelector, ProcessLauncher, WindowManager},
};

pub fn is_explicit_path(name: &str) -> bool {
    name.ends_with(".yml") || name.ends_with(".yaml") || name.contains('/')
}

pub fn load_layout(repository: &dyn ConfigRepository, name: &str) -> Result<LayoutConfig> {
    if is_explicit_path(name) {
        repository.load_path(Path::new(name))
    } else {
        repository.load_named(name)
    }
}

pub fn template(name: &str) -> String {
    format!(
        "name: {name}\n# workspace: 3\n# workspace_name: \"\"\nterminal: wezterm\n\nlayout:\n  split: horizontal\n  children:\n    - window:\n        command: \"\"\n        type: terminal\n        ratio: 50\n    - window:\n        command: \"\"\n        type: terminal\n        ratio: 50\n"
    )
}

pub fn create(repository: &dyn ConfigRepository, name: &str) -> Result<PathBuf> {
    repository.create(name, &template(name))
}

pub fn edit(
    repository: &dyn ConfigRepository,
    editor: &dyn Editor,
    name: &str,
) -> Result<(PathBuf, bool)> {
    let path = repository.path_for(name)?;
    let created = !path.exists();
    if created {
        repository.create(name, &template(name))?;
    }
    let status = editor.edit(&path)?;
    if !status.success() {
        return Err(WminatorError::EditorFailed(status.code().unwrap_or(1)));
    }
    Ok((path, created))
}

pub fn rofi(
    repository: &dyn ConfigRepository,
    selector: &dyn MenuSelector,
    prompt: &str,
    theme: &str,
) -> Result<Option<String>> {
    selector.select(&repository.list()?, prompt, theme)
}

pub fn expand_command(command: &str) -> String {
    let expanded = if let Some(rest) = command.strip_prefix("~/") {
        env::var("HOME").map_or_else(|_| command.to_owned(), |home| format!("{home}/{rest}"))
    } else {
        command.to_owned()
    };
    let mut result = String::with_capacity(expanded.len());
    let mut characters = expanded.chars().peekable();
    while let Some(character) = characters.next() {
        if character != '$' {
            result.push(character);
            continue;
        }
        let braced = characters.peek() == Some(&'{');
        if braced {
            characters.next();
        }
        let mut name = String::new();
        while let Some(next) = characters.peek().copied() {
            if (next == '_' || next.is_ascii_alphanumeric())
                && (!name.is_empty() || !next.is_ascii_digit())
            {
                name.push(next);
                characters.next();
            } else {
                break;
            }
        }
        if braced && characters.peek() == Some(&'}') {
            characters.next();
        }
        if name.is_empty() {
            result.push('$');
            if braced {
                result.push('{');
            }
        } else if let Ok(value) = env::var(&name) {
            result.push_str(&value);
        } else {
            result.push('$');
            if braced {
                result.push('{');
            }
            result.push_str(&name);
            if braced {
                result.push('}');
            }
        }
    }
    result
}

pub fn build_process_argv(window: &Window, terminal: &str) -> Result<Vec<String>> {
    let command = expand_command(&window.command);
    match window.kind {
        WindowType::App => {
            shell_words::split(&command).map_err(|error| WminatorError::CommandLine {
                command,
                message: error.to_string(),
            })
        }
        WindowType::Terminal => {
            let term = terminal.to_lowercase();
            let argv = match term.as_str() {
                "wezterm" | "wezterm-gui" => vec!["wezterm", "start", "--", "sh", "-c", &command],
                "alacritty" => vec!["alacritty", "-e", "sh", "-c", &command],
                "kitty" => vec!["kitty", "sh", "-c", &command],
                "st" | "suckless" => vec!["st", "-e", "sh", "-c", &command],
                "xterm" => vec!["xterm", "-e", &command],
                _ => vec![terminal, "-e", "sh", "-c", &command],
            };
            Ok(argv.into_iter().map(ToOwned::to_owned).collect())
        }
    }
}

pub async fn open(
    wm: &mut dyn WindowManager,
    launcher: &dyn ProcessLauncher,
    config: &LayoutConfig,
    force: bool,
) -> Result<()> {
    ensure_workspace_available(wm, config.workspace, force).await?;
    switch_workspace(wm, config.workspace, config.workspace_name.as_deref()).await?;
    apply_container(wm, launcher, &config.layout, &config.terminal).await
}

async fn ensure_workspace_available(
    wm: &mut dyn WindowManager,
    number: Option<i32>,
    force: bool,
) -> Result<()> {
    if force {
        return Ok(());
    }
    let target = if let Some(number) = number {
        wm.workspaces()
            .await?
            .into_iter()
            .find(|workspace| workspace.number == Some(number))
    } else {
        Some(wm.focused_workspace().await?)
    };
    if target.is_some_and(|workspace| !workspace.window_ids.is_empty()) {
        let label = number.map_or_else(
            || "current workspace".to_owned(),
            |number| format!("workspace {number}"),
        );
        return Err(WminatorError::WorkspaceOccupied(label));
    }
    Ok(())
}

async fn switch_workspace(
    wm: &mut dyn WindowManager,
    number: Option<i32>,
    name: Option<&str>,
) -> Result<()> {
    if let Some(number) = number {
        wm.command(&format!("workspace number {number}")).await?;
    }
    if let Some(name) = name {
        let number = wm.focused_workspace().await?.number;
        let target = number.map_or_else(|| name.to_owned(), |number| format!("{number}:{name}"));
        wm.command(&format!(
            "rename workspace to \"{}\"",
            escape_command_string(&target)
        ))
        .await?;
    }
    Ok(())
}

#[async_recursion(?Send)]
async fn apply_container(
    wm: &mut dyn WindowManager,
    launcher: &dyn ProcessLauncher,
    container: &Container,
    terminal: &str,
) -> Result<()> {
    let axis = container.axis();
    for (index, child) in container.children.iter().enumerate() {
        if index > 0 {
            wm.command(match axis {
                Axis::Horizontal => "split h",
                Axis::Vertical => "split v",
            })
            .await?;
        }
        match (&child.window, &child.container) {
            (Some(window), None) => {
                let argv = build_process_argv(window, terminal)?;
                wm.launch_and_wait(launcher, &argv, window.match_rule.as_ref(), window.timeout)
                    .await?;
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            (None, Some(container)) => apply_container(wm, launcher, container, terminal).await?,
            _ => {
                return Err(WminatorError::InvalidConfig {
                    path: PathBuf::from("<config>"),
                    message: format!("layout child {index} is invalid"),
                });
            }
        }
    }
    if let Some(layout) = container.layout {
        wm.command("focus parent").await?;
        let layout = match layout {
            ContainerLayout::Splith => "splith",
            ContainerLayout::Splitv => "splitv",
            ContainerLayout::Stacked => "stacked",
            ContainerLayout::Tabbed => "tabbed",
        };
        wm.command(&format!("layout {layout}")).await?;
        wm.command("focus child").await?;
    }
    if let Some(ratios) = container
        .normalized_ratios()
        .filter(|_| container.children.len() > 1)
    {
        wm.command("focus parent").await?;
        wm.command("focus child").await?;
        for (index, ratio) in ratios.into_iter().enumerate() {
            let axis_name = match axis {
                Axis::Horizontal => "width",
                Axis::Vertical => "height",
            };
            wm.command(&format!(
                "resize set {axis_name} {} ppt",
                ratio.round() as u32
            ))
            .await?;
            if index + 1 < container.children.len() {
                wm.command(match axis {
                    Axis::Horizontal => "focus right",
                    Axis::Vertical => "focus down",
                })
                .await?;
            }
        }
    }
    Ok(())
}

fn escape_command_string(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

pub fn selected_backend(
    explicit: Option<Backend>,
    sway_socket: Option<&str>,
    i3_socket: Option<&str>,
    i3_version_human: Option<&str>,
) -> Result<Backend> {
    if let Some(backend) = explicit {
        return Ok(backend);
    }
    if sway_socket.is_some_and(|socket| !socket.is_empty()) {
        return Ok(Backend::Sway);
    }
    if i3_socket.is_some_and(|socket| !socket.is_empty()) {
        return Ok(
            if i3_version_human.is_some_and(|version| version.to_lowercase().contains("sway")) {
                Backend::Sway
            } else {
                Backend::I3
            },
        );
    }
    Err(WminatorError::BackendUnavailable)
}
