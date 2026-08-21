use async_trait::async_trait;
#[cfg(unix)]
use std::os::unix::process::ExitStatusExt;
use std::{cell::RefCell, collections::HashSet, path::Path, process::ExitStatus};
use wminator::{
    Result as WResult,
    adapters::YamlConfigRepository,
    application::{build_process_argv, edit, expand_command, open, rofi, selected_backend},
    domain::{
        Backend, LayoutConfig, MatchRule, Window, WindowProperties, WindowType, WorkspaceSnapshot,
    },
    ports::{Editor, MenuSelector, ProcessLauncher, WindowManager},
};

type TestResult = std::result::Result<(), Box<dyn std::error::Error>>;

struct SuccessfulEditor;
impl Editor for SuccessfulEditor {
    fn edit(&self, _path: &Path) -> WResult<ExitStatus> {
        Ok(ExitStatus::from_raw(0))
    }
}

struct FakeMenu(Option<String>);
impl MenuSelector for FakeMenu {
    fn select(&self, _choices: &[String], _prompt: &str, _theme: &str) -> WResult<Option<String>> {
        Ok(self.0.clone())
    }
}

#[derive(Default)]
struct FakeLauncher {
    launched: RefCell<Vec<Vec<String>>>,
}
#[async_trait(?Send)]
impl ProcessLauncher for FakeLauncher {
    async fn spawn_detached(&self, argv: &[String]) -> WResult<()> {
        self.launched.borrow_mut().push(argv.to_vec());
        Ok(())
    }
}

struct FakeWm {
    commands: Vec<String>,
    occupied: bool,
    backend: Backend,
}
#[async_trait(?Send)]
impl WindowManager for FakeWm {
    fn backend(&self) -> Backend {
        self.backend
    }
    async fn command(&mut self, command: &str) -> WResult<()> {
        self.commands.push(command.to_owned());
        Ok(())
    }
    async fn workspaces(&mut self) -> WResult<Vec<WorkspaceSnapshot>> {
        Ok(vec![workspace(self.occupied)])
    }
    async fn focused_workspace(&mut self) -> WResult<WorkspaceSnapshot> {
        Ok(workspace(self.occupied))
    }
    async fn window_ids(&mut self) -> WResult<HashSet<i64>> {
        Ok(HashSet::new())
    }
    async fn launch_and_wait(
        &mut self,
        launcher: &dyn ProcessLauncher,
        argv: &[String],
        _rule: Option<&MatchRule>,
        _timeout: f64,
    ) -> WResult<WindowProperties> {
        launcher.spawn_detached(argv).await?;
        Ok(WindowProperties {
            id: 42,
            ..WindowProperties::default()
        })
    }
}

fn workspace(occupied: bool) -> WorkspaceSnapshot {
    WorkspaceSnapshot {
        number: Some(3),
        name: "3".to_owned(),
        focused: true,
        window_ids: if occupied {
            HashSet::from([1])
        } else {
            HashSet::new()
        },
    }
}

fn config() -> std::result::Result<LayoutConfig, yaml_serde::Error> {
    yaml_serde::from_str(
        "name: test\nworkspace: 3\nworkspace_name: dev\nlayout:\n  split: vertical\n  children:\n    - window: { command: one, ratio: 40 }\n    - window: { command: two, ratio: 60 }\n",
    )
}

#[test]
fn terminal_argument_conventions_are_preserved() -> TestResult {
    let window = Window {
        command: "echo hi".to_owned(),
        kind: WindowType::Terminal,
        ratio: None,
        match_rule: None,
        timeout: 10.0,
    };
    assert_eq!(
        build_process_argv(&window, "wezterm")?,
        ["wezterm", "start", "--", "sh", "-c", "echo hi"]
    );
    assert_eq!(
        build_process_argv(&window, "alacritty")?,
        ["alacritty", "-e", "sh", "-c", "echo hi"]
    );
    assert_eq!(
        build_process_argv(&window, "kitty")?,
        ["kitty", "sh", "-c", "echo hi"]
    );
    assert_eq!(
        build_process_argv(&window, "st")?,
        ["st", "-e", "sh", "-c", "echo hi"]
    );
    assert_eq!(
        build_process_argv(&window, "xterm")?,
        ["xterm", "-e", "echo hi"]
    );
    assert_eq!(
        build_process_argv(&window, "foot")?,
        ["foot", "-e", "sh", "-c", "echo hi"]
    );
    Ok(())
}

#[test]
fn app_commands_use_shell_word_parsing() -> TestResult {
    let window = Window {
        command: "browser --title 'two words'".to_owned(),
        kind: WindowType::App,
        ratio: None,
        match_rule: None,
        timeout: 10.0,
    };
    assert_eq!(
        build_process_argv(&window, "ignored")?,
        ["browser", "--title", "two words"]
    );
    Ok(())
}

#[test]
fn command_expansion_handles_braced_and_prefix_variables() -> TestResult {
    let home = std::env::var("HOME")?;
    assert_eq!(expand_command("$HOME/${HOME}"), format!("{home}/{home}"));
    assert_eq!(
        expand_command("$WMINATOR_MISSING_VAR/${WMINATOR_MISSING_VAR}"),
        "$WMINATOR_MISSING_VAR/${WMINATOR_MISSING_VAR}"
    );
    Ok(())
}

#[test]
fn editor_creates_template_and_menu_cancellation_is_success() -> TestResult {
    let directory = tempfile::tempdir()?;
    let repository = YamlConfigRepository::new(directory.path().to_owned());
    let (path, created) = edit(&repository, &SuccessfulEditor, "new-layout")?;
    assert!(created);
    assert!(path.is_file());
    assert_eq!(
        rofi(&repository, &FakeMenu(None), "wminator:", "theme")?,
        None
    );
    assert_eq!(
        rofi(
            &repository,
            &FakeMenu(Some("new-layout".to_owned())),
            "wminator:",
            "theme"
        )?,
        Some("new-layout".to_owned())
    );
    Ok(())
}

#[test]
fn backend_precedence_and_classification() -> TestResult {
    assert_eq!(
        selected_backend(Some(Backend::I3), Some("sway"), None, None)?,
        Backend::I3
    );
    assert_eq!(
        selected_backend(None, Some("sway"), Some("i3"), None)?,
        Backend::Sway
    );
    assert_eq!(
        selected_backend(None, None, Some("i3"), Some("sway version 1.9"))?,
        Backend::Sway
    );
    assert_eq!(
        selected_backend(None, None, Some("i3"), Some("4.24"))?,
        Backend::I3
    );
    assert!(selected_backend(None, Some(""), Some(""), None).is_err());
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn applies_workspace_layout_and_ratios_sequentially() -> TestResult {
    let mut wm = FakeWm {
        commands: Vec::new(),
        occupied: false,
        backend: Backend::I3,
    };
    let launcher = FakeLauncher::default();
    open(&mut wm, &launcher, &config()?, false).await?;
    assert_eq!(launcher.launched.borrow().len(), 2);
    assert_eq!(
        wm.commands,
        [
            "workspace number 3",
            "rename workspace to \"3:dev\"",
            "split v",
            "focus parent",
            "focus child",
            "resize set height 40 ppt",
            "focus down",
            "resize set height 60 ppt"
        ]
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn occupancy_check_honors_force() -> TestResult {
    let launcher = FakeLauncher::default();
    let mut blocked = FakeWm {
        commands: Vec::new(),
        occupied: true,
        backend: Backend::I3,
    };
    assert!(
        open(&mut blocked, &launcher, &config()?, false)
            .await
            .is_err()
    );
    let mut forced = FakeWm {
        commands: Vec::new(),
        occupied: true,
        backend: Backend::I3,
    };
    open(&mut forced, &launcher, &config()?, true).await?;
    assert!(!forced.commands.is_empty());
    Ok(())
}
