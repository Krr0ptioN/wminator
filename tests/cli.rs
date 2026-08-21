use std::{fs, process::Command};
use tempfile::tempdir;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_wminator")
}

#[test]
fn list_create_validate_and_errors_have_expected_statuses() -> Result<(), Box<dyn std::error::Error>>
{
    let directory = tempdir()?;
    let output = Command::new(binary())
        .arg("list")
        .env("WMINATOR_CONFIG_DIR", directory.path())
        .output()?;
    assert!(output.status.success());
    assert_eq!(String::from_utf8(output.stdout)?, "No layouts found.\n");

    let output = Command::new(binary())
        .args(["create", "demo"])
        .env("WMINATOR_CONFIG_DIR", directory.path())
        .output()?;
    assert!(output.status.success());
    assert!(directory.path().join("demo.yml").is_file());

    let output = Command::new(binary())
        .args(["validate", "demo"])
        .env("WMINATOR_CONFIG_DIR", directory.path())
        .output()?;
    assert!(output.status.success());
    assert_eq!(String::from_utf8(output.stdout)?, "'demo' is valid\n");

    fs::write(
        directory.path().join("bad.yml"),
        "name: bad\nlayout:\n  children: []\n",
    )?;
    let output = Command::new(binary())
        .args(["validate", "bad"])
        .env("WMINATOR_CONFIG_DIR", directory.path())
        .output()?;
    assert!(!output.status.success());
    assert!(String::from_utf8(output.stderr)?.contains("layout.children"));
    Ok(())
}

#[test]
fn clap_reports_version_and_parse_errors() -> Result<(), Box<dyn std::error::Error>> {
    let version = Command::new(binary()).arg("--version").output()?;
    assert!(version.status.success());
    assert_eq!(String::from_utf8(version.stdout)?, "wminator 0.1.0\n");
    let invalid = Command::new(binary()).arg("missing-command").output()?;
    assert!(!invalid.status.success());
    assert!(String::from_utf8(invalid.stderr)?.contains("unrecognized subcommand"));
    Ok(())
}
