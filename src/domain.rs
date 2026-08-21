use serde::Deserialize;
use std::collections::HashSet;

use crate::error::{Result, WminatorError};

fn default_terminal() -> String {
    "wezterm".to_owned()
}
fn default_timeout() -> f64 {
    10.0
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LayoutConfig {
    pub name: String,
    pub workspace: Option<i32>,
    pub workspace_name: Option<String>,
    #[serde(default = "default_terminal")]
    pub terminal: String,
    pub layout: Container,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Container {
    pub split: Option<Split>,
    pub layout: Option<ContainerLayout>,
    pub ratio: Option<f64>,
    pub children: Vec<Child>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Child {
    pub window: Option<Window>,
    pub container: Option<Container>,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Split {
    Horizontal,
    Vertical,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ContainerLayout {
    Splith,
    Splitv,
    Stacked,
    Tabbed,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Window {
    pub command: String,
    #[serde(rename = "type", default)]
    pub kind: WindowType,
    pub ratio: Option<f64>,
    #[serde(rename = "match")]
    pub match_rule: Option<MatchRule>,
    #[serde(default = "default_timeout")]
    pub timeout: f64,
}

#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum WindowType {
    #[default]
    Terminal,
    App,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MatchRule {
    pub class: Option<String>,
    pub title: Option<String>,
    pub instance: Option<String>,
    pub app_id: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Axis {
    Horizontal,
    Vertical,
}

impl Container {
    pub fn axis(&self) -> Axis {
        match (self.split, self.layout) {
            (Some(Split::Vertical), _)
            | (
                None,
                Some(ContainerLayout::Splitv | ContainerLayout::Stacked | ContainerLayout::Tabbed),
            ) => Axis::Vertical,
            _ => Axis::Horizontal,
        }
    }

    pub fn validate(&self, path: &str) -> std::result::Result<(), String> {
        validate_ratio(self.ratio, &format!("{path}.ratio"))?;
        if self.children.is_empty() {
            return Err(format!("{path}.children: must be a non-empty list"));
        }
        for (index, child) in self.children.iter().enumerate() {
            match (&child.window, &child.container) {
                (Some(window), None) => {
                    window.validate(&format!("{path}.children[{index}].window"))?
                }
                (None, Some(container)) => {
                    container.validate(&format!("{path}.children[{index}].container"))?
                }
                (Some(_), Some(_)) => {
                    return Err(format!(
                        "{path}.children[{index}]: cannot have both 'window' and 'container'"
                    ));
                }
                (None, None) => {
                    return Err(format!(
                        "{path}.children[{index}]: must have 'window' or 'container'"
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn normalized_ratios(&self) -> Option<Vec<f64>> {
        let raw: Vec<Option<f64>> = self.children.iter().map(Child::ratio).collect();
        if raw.iter().all(Option::is_none) {
            return None;
        }
        let explicit: f64 = raw.iter().flatten().sum();
        let missing = raw.iter().filter(|value| value.is_none()).count();
        let fill = if missing == 0 {
            0.0
        } else {
            (100.0 - explicit).max(0.0) / missing as f64
        };
        let mut values: Vec<f64> = raw.into_iter().map(|value| value.unwrap_or(fill)).collect();
        let total: f64 = values.iter().sum();
        if total > 0.0 {
            values
                .iter_mut()
                .for_each(|value| *value = *value / total * 100.0);
        }
        Some(values)
    }
}

impl Child {
    pub fn ratio(&self) -> Option<f64> {
        self.window
            .as_ref()
            .and_then(|window| window.ratio)
            .or_else(|| {
                self.container
                    .as_ref()
                    .and_then(|container| container.ratio)
            })
    }
}

impl Window {
    fn validate(&self, path: &str) -> std::result::Result<(), String> {
        validate_ratio(self.ratio, &format!("{path}.ratio"))?;
        if !self.timeout.is_finite() || self.timeout <= 0.0 {
            return Err(format!("{path}.timeout: must be positive and finite"));
        }
        if let Some(rule) = &self.match_rule {
            let values = [&rule.class, &rule.title, &rule.instance, &rule.app_id];
            if values.into_iter().flatten().any(String::is_empty) {
                return Err(format!("{path}.match: criteria must not be empty"));
            }
        }
        Ok(())
    }
}

fn validate_ratio(value: Option<f64>, path: &str) -> std::result::Result<(), String> {
    if let Some(value) = value {
        if !value.is_finite() || value <= 0.0 || value > 100.0 {
            return Err(format!("{path}: must be a number between 0 and 100"));
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WindowProperties {
    pub id: i64,
    pub class: Option<String>,
    pub title: Option<String>,
    pub instance: Option<String>,
    pub app_id: Option<String>,
}

impl WindowProperties {
    pub fn matches(&self, rule: Option<&MatchRule>, backend: Backend) -> Result<bool> {
        let Some(rule) = rule else { return Ok(true) };
        if backend == Backend::I3 && rule.app_id.is_some() {
            return Err(WminatorError::UnsupportedAppId);
        }
        let class = match backend {
            Backend::I3 => self.class.as_deref(),
            Backend::Sway => self.class.as_deref().or(self.app_id.as_deref()),
        };
        Ok(matches_part(class, rule.class.as_deref())
            && matches_part(self.title.as_deref(), rule.title.as_deref())
            && matches_part(self.instance.as_deref(), rule.instance.as_deref())
            && matches_part(self.app_id.as_deref(), rule.app_id.as_deref()))
    }
}

fn matches_part(actual: Option<&str>, wanted: Option<&str>) -> bool {
    wanted.is_none_or(|wanted| {
        actual.is_some_and(|actual| actual.to_lowercase().contains(&wanted.to_lowercase()))
    })
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WorkspaceSnapshot {
    pub number: Option<i32>,
    pub name: String,
    pub focused: bool,
    pub window_ids: HashSet<i64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum Backend {
    I3,
    Sway,
}
