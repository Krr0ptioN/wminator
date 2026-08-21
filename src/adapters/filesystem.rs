use std::{
    env, fs,
    path::{Path, PathBuf},
};

use crate::{
    domain::LayoutConfig,
    error::{Result, WminatorError},
    ports::ConfigRepository,
};

#[derive(Debug, Clone)]
pub struct YamlConfigRepository {
    root: PathBuf,
}

impl YamlConfigRepository {
    pub fn from_environment() -> Self {
        let root = env::var_os("WMINATOR_CONFIG_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                env::var_os("HOME")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."))
                    .join(".config/wminator")
            });
        Self { root }
    }
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    fn ensure_directory(&self) -> Result<()> {
        fs::create_dir_all(&self.root).map_err(|error| io_error(&self.root, error))
    }

    fn parse(&self, path: &Path) -> Result<LayoutConfig> {
        let contents = fs::read_to_string(path).map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                WminatorError::ConfigNotFound(path.to_owned())
            } else {
                io_error(path, error)
            }
        })?;
        let deserializer = yaml_serde::Deserializer::from_str(&contents);
        let parsed =
            serde_path_to_error::deserialize::<_, LayoutConfig>(deserializer).map_err(|error| {
                WminatorError::InvalidConfig {
                    path: path.to_owned(),
                    message: format!("{}: {}", error.path(), error.inner()),
                }
            })?;
        parsed
            .layout
            .validate("layout")
            .map_err(|message| WminatorError::InvalidConfig {
                path: path.to_owned(),
                message,
            })?;
        Ok(parsed)
    }
}

impl ConfigRepository for YamlConfigRepository {
    fn directory(&self) -> Result<PathBuf> {
        self.ensure_directory()?;
        Ok(self.root.clone())
    }
    fn list(&self) -> Result<Vec<String>> {
        self.ensure_directory()?;
        let mut names = Vec::new();
        let entries = fs::read_dir(&self.root).map_err(|error| io_error(&self.root, error))?;
        for entry in entries {
            let entry = entry.map_err(|error| io_error(&self.root, error))?;
            let path = entry.path();
            if path.is_file() && path.extension().is_some_and(|extension| extension == "yml") {
                if let Some(stem) = path.file_stem().and_then(|value| value.to_str()) {
                    names.push(stem.to_owned());
                }
            }
        }
        names.sort();
        Ok(names)
    }
    fn load_named(&self, name: &str) -> Result<LayoutConfig> {
        self.parse(&self.root.join(format!("{name}.yml")))
    }
    fn load_path(&self, path: &Path) -> Result<LayoutConfig> {
        self.parse(&expand_path(path))
    }
    fn create(&self, name: &str, contents: &str) -> Result<PathBuf> {
        self.ensure_directory()?;
        let path = self.root.join(format!("{name}.yml"));
        if path.exists() {
            return Err(WminatorError::InvalidConfig {
                path,
                message: format!("layout '{name}' already exists"),
            });
        }
        fs::write(&path, contents).map_err(|error| io_error(&path, error))?;
        Ok(path)
    }
    fn path_for(&self, name: &str) -> Result<PathBuf> {
        self.ensure_directory()?;
        Ok(self.root.join(format!("{name}.yml")))
    }
}

fn expand_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix("~/") {
        if let Some(home) = env::var_os("HOME") {
            return PathBuf::from(home).join(rest);
        }
    }
    path.to_owned()
}

fn io_error(path: &Path, error: std::io::Error) -> WminatorError {
    WminatorError::Io {
        path: path.to_owned(),
        message: error.to_string(),
    }
}
