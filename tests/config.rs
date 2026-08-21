use std::{fs, path::Path};
use tempfile::tempdir;
use wminator::{
    adapters::YamlConfigRepository,
    domain::{Backend, MatchRule, WindowProperties},
    ports::ConfigRepository,
};

const VALID: &str = r#"
name: dev
workspace: 3
workspace_name: code
terminal: kitty
layout:
  split: horizontal
  children:
    - window:
        command: nvim
        ratio: 60
    - container:
        layout: tabbed
        ratio: 40
        children:
          - window:
              command: firefox
              type: app
              timeout: 2.5
              match:
                class: Firefox
                title: Docs
                instance: navigator
                app_id: firefox
"#;

#[test]
fn loads_typed_nested_layout() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempdir()?;
    fs::write(directory.path().join("dev.yml"), VALID)?;
    let repository = YamlConfigRepository::new(directory.path().to_owned());
    let config = repository.load_named("dev")?;
    assert_eq!(config.name, "dev");
    assert_eq!(config.workspace, Some(3));
    assert_eq!(config.layout.children.len(), 2);
    assert_eq!(config.layout.normalized_ratios(), Some(vec![60.0, 40.0]));
    Ok(())
}

#[test]
fn lists_only_sorted_yml_files() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempdir()?;
    fs::write(directory.path().join("z.yml"), VALID)?;
    fs::write(directory.path().join("a.yml"), VALID)?;
    fs::write(directory.path().join("ignored.yaml"), VALID)?;
    let repository = YamlConfigRepository::new(directory.path().to_owned());
    assert_eq!(repository.list()?, vec!["a", "z"]);
    Ok(())
}

#[test]
fn rejects_unknown_key_with_file_and_field_path() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("bad.yml");
    fs::write(
        &path,
        VALID.replace("command: nvim", "command: nvim\n        surprise: true"),
    )?;
    let repository = YamlConfigRepository::new(directory.path().to_owned());
    let error = repository
        .load_path(&path)
        .err()
        .ok_or("expected validation error")?
        .to_string();
    assert!(error.contains(path.to_string_lossy().as_ref()));
    assert!(error.contains("surprise"), "{error}");
    assert!(error.contains("layout.children[0]"));
    Ok(())
}

#[test]
fn rejects_empty_container_and_invalid_numeric_values() -> Result<(), Box<dyn std::error::Error>> {
    for (name, yaml, expected) in [
        (
            "empty",
            "name: x\nlayout:\n  children: []\n",
            "layout.children",
        ),
        (
            "ratio",
            "name: x\nlayout:\n  children:\n    - window:\n        command: x\n        ratio: 0\n",
            "ratio",
        ),
        (
            "timeout",
            "name: x\nlayout:\n  children:\n    - window:\n        command: x\n        timeout: .nan\n",
            "timeout",
        ),
    ] {
        let directory = tempdir()?;
        let path = directory.path().join(format!("{name}.yml"));
        fs::write(&path, yaml)?;
        let repository = YamlConfigRepository::new(directory.path().to_owned());
        let error = repository
            .load_path(&path)
            .err()
            .ok_or("expected validation error")?
            .to_string();
        assert!(error.contains(expected));
    }
    Ok(())
}

#[test]
fn missing_ratios_share_remainder_and_values_normalize() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempdir()?;
    let yaml = "name: x\nlayout:\n  children:\n    - window: { command: a, ratio: 1 }\n    - window: { command: b, ratio: 1 }\n";
    fs::write(directory.path().join("x.yml"), yaml)?;
    let repository = YamlConfigRepository::new(directory.path().to_owned());
    assert_eq!(
        repository.load_named("x")?.layout.normalized_ratios(),
        Some(vec![50.0, 50.0])
    );

    let yaml = "name: y\nlayout:\n  children:\n    - window: { command: a, ratio: 60 }\n    - window: { command: b }\n";
    fs::write(directory.path().join("y.yml"), yaml)?;
    assert_eq!(
        repository.load_named("y")?.layout.normalized_ratios(),
        Some(vec![60.0, 40.0])
    );
    Ok(())
}

#[test]
fn matching_is_backend_specific_and_case_insensitive() -> Result<(), Box<dyn std::error::Error>> {
    let window = WindowProperties {
        id: 1,
        class: None,
        title: Some("Project Docs".to_owned()),
        instance: None,
        app_id: Some("org.FOOT".to_owned()),
    };
    let rule = MatchRule {
        class: Some("foot".to_owned()),
        title: Some("docs".to_owned()),
        ..MatchRule::default()
    };
    assert!(window.matches(Some(&rule), Backend::Sway)?);
    assert!(!window.matches(Some(&rule), Backend::I3)?);
    let app_rule = MatchRule {
        app_id: Some("foot".to_owned()),
        ..MatchRule::default()
    };
    assert!(window.matches(Some(&app_rule), Backend::I3).is_err());
    Ok(())
}

#[test]
fn explicit_yaml_paths_are_accepted() {
    assert!(wminator::application::is_explicit_path("a.yml"));
    assert!(wminator::application::is_explicit_path("a.yaml"));
    assert!(wminator::application::is_explicit_path("layouts/a"));
    assert!(!wminator::application::is_explicit_path("a"));
    assert_eq!(Path::new("a").extension(), None);
}
