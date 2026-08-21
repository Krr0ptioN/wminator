use async_trait::async_trait;
use std::{
    env,
    path::Path,
    process::{Command, ExitStatus, Stdio},
};

use crate::{
    error::{Result, WminatorError},
    ports::{Editor, MenuSelector, ProcessLauncher},
};

#[derive(Debug, Default)]
pub struct OsProcessLauncher;

#[async_trait(?Send)]
impl ProcessLauncher for OsProcessLauncher {
    async fn spawn_detached(&self, argv: &[String]) -> Result<()> {
        let Some(program) = argv.first() else {
            return Err(WminatorError::CommandLine {
                command: String::new(),
                message: "empty command".to_owned(),
            });
        };
        let mut command = tokio::process::Command::new(program);
        command
            .args(&argv[1..])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(unix)]
        {
            command.process_group(0);
        }
        command.spawn().map(|_| ()).map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                WminatorError::CommandNotFound(program.clone())
            } else {
                WminatorError::Spawn {
                    program: program.clone(),
                    message: error.to_string(),
                }
            }
        })
    }
}

#[derive(Debug, Default)]
pub struct OsEditor;
impl Editor for OsEditor {
    fn edit(&self, path: &Path) -> Result<ExitStatus> {
        let editor = env::var("EDITOR").unwrap_or_else(|_| "vim".to_owned());
        let argv = shell_words::split(&editor).map_err(|error| WminatorError::CommandLine {
            command: editor.clone(),
            message: error.to_string(),
        })?;
        let Some(program) = argv.first() else {
            return Err(WminatorError::EditorNotFound(editor));
        };
        Command::new(program)
            .args(&argv[1..])
            .arg(path)
            .status()
            .map_err(|error| {
                if error.kind() == std::io::ErrorKind::NotFound {
                    WminatorError::EditorNotFound(program.clone())
                } else {
                    WminatorError::Spawn {
                        program: program.clone(),
                        message: error.to_string(),
                    }
                }
            })
    }
}

#[derive(Debug, Default)]
pub struct RofiSelector;
impl MenuSelector for RofiSelector {
    fn select(&self, choices: &[String], prompt: &str, theme: &str) -> Result<Option<String>> {
        if choices.is_empty() {
            return Ok(None);
        }
        let mut child = match Command::new("rofi")
            .args(["-dmenu", "-i", "-p", prompt, "-theme", theme])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => {
                return Err(WminatorError::Spawn {
                    program: "rofi".to_owned(),
                    message: error.to_string(),
                });
            }
        };
        if let Some(mut stdin) = child.stdin.take() {
            use std::io::Write;
            stdin
                .write_all(choices.join("\n").as_bytes())
                .map_err(|error| WminatorError::Spawn {
                    program: "rofi".to_owned(),
                    message: error.to_string(),
                })?;
        }
        let output = child
            .wait_with_output()
            .map_err(|error| WminatorError::Spawn {
                program: "rofi".to_owned(),
                message: error.to_string(),
            })?;
        if !output.status.success() {
            return Ok(None);
        }
        let selected = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        Ok((!selected.is_empty()).then_some(selected))
    }
}
