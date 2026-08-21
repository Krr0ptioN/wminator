//! Opt-in smoke test. It deliberately leaves window-launch and workspace cleanup to
//! a configured command so it cannot affect a real session accidentally.

use std::env;
use wminator::{adapters::connect, domain::Backend};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires a live i3 or Sway session"]
async fn live_connection_workspace_and_command() -> Result<(), Box<dyn std::error::Error>> {
    let backend = match env::var("WMINATOR_LIVE_BACKEND").as_deref() {
        Ok("i3") => Backend::I3,
        Ok("sway") => Backend::Sway,
        _ => return Err("set WMINATOR_LIVE_BACKEND=i3|sway".into()),
    };
    let mut wm = connect(Some(backend)).await?;
    let workspaces = wm.workspaces().await?;
    assert!(!workspaces.is_empty());
    wm.command("nop wminator live smoke").await?;
    Ok(())
}
