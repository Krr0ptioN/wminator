use async_trait::async_trait;
use std::{
    path::{Path, PathBuf},
    process::ExitStatus,
};

use crate::{
    Result,
    domain::{Backend, LayoutConfig, MatchRule, WindowProperties, WorkspaceSnapshot},
};

pub trait ConfigRepository {
    fn directory(&self) -> Result<PathBuf>;
    fn list(&self) -> Result<Vec<String>>;
    fn load_named(&self, name: &str) -> Result<LayoutConfig>;
    fn load_path(&self, path: &Path) -> Result<LayoutConfig>;
    fn create(&self, name: &str, contents: &str) -> Result<PathBuf>;
    fn path_for(&self, name: &str) -> Result<PathBuf>;
}

#[async_trait(?Send)]
pub trait WindowManager {
    fn backend(&self) -> Backend;
    async fn command(&mut self, command: &str) -> Result<()>;
    async fn workspaces(&mut self) -> Result<Vec<WorkspaceSnapshot>>;
    async fn focused_workspace(&mut self) -> Result<WorkspaceSnapshot>;
    async fn window_ids(&mut self) -> Result<std::collections::HashSet<i64>>;
    async fn launch_and_wait(
        &mut self,
        launcher: &dyn ProcessLauncher,
        argv: &[String],
        rule: Option<&MatchRule>,
        timeout: f64,
    ) -> Result<WindowProperties>;
}

#[async_trait(?Send)]
pub trait ProcessLauncher {
    async fn spawn_detached(&self, argv: &[String]) -> Result<()>;
}

pub trait Editor {
    fn edit(&self, path: &Path) -> Result<ExitStatus>;
}

pub trait MenuSelector {
    fn select(&self, choices: &[String], prompt: &str, theme: &str) -> Result<Option<String>>;
}
