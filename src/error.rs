use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum WminatorError {
    #[error("layout config not found: {0}")]
    ConfigNotFound(PathBuf),
    #[error("{path}: {message}")]
    InvalidConfig { path: PathBuf, message: String },
    #[error(
        "cannot determine window-manager backend; use --backend i3|sway or set SWAYSOCK/I3SOCK"
    )]
    BackendUnavailable,
    #[error("cannot connect to {backend}: {message}")]
    Connection { backend: String, message: String },
    #[error("i3 does not support match.app_id")]
    UnsupportedAppId,
    #[error("window-manager command `{command}` was rejected: {reply}")]
    CommandRejected { command: String, reply: String },
    #[error("window-manager IPC disconnected: {0}")]
    Disconnected(String),
    #[error("command not found: {0}")]
    CommandNotFound(String),
    #[error("failed to spawn {program}: {message}")]
    Spawn { program: String, message: String },
    #[error("window did not appear within {timeout}s: {command}")]
    LaunchTimeout { timeout: f64, command: String },
    #[error("{0} is not empty (use --force to override)")]
    WorkspaceOccupied(String),
    #[error("no focused workspace found")]
    NoFocusedWorkspace,
    #[error("editor not found: {0}")]
    EditorNotFound(String),
    #[error("editor exited with code {0}")]
    EditorFailed(i32),
    #[error("I/O error at {path}: {message}")]
    Io { path: PathBuf, message: String },
    #[error("invalid command line `{command}`: {message}")]
    CommandLine { command: String, message: String },
}

pub type Result<T> = std::result::Result<T, WminatorError>;
