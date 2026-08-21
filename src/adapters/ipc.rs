use async_trait::async_trait;
use futures_util::StreamExt;
use std::{collections::HashSet, env, time::Duration};
use swayipc_async::{Connection, Event, EventType, Node, NodeType, WindowChange};

use crate::{
    application::selected_backend,
    domain::{Backend, MatchRule, WindowProperties, WorkspaceSnapshot},
    error::{Result, WminatorError},
    ports::{ProcessLauncher, WindowManager},
};

pub struct I3Adapter {
    connection: Connection,
}
pub struct SwayAdapter {
    connection: Connection,
}

pub async fn connect(explicit: Option<Backend>) -> Result<Box<dyn WindowManager>> {
    let sway_socket = env::var("SWAYSOCK").ok();
    let i3_socket = env::var("I3SOCK").ok();
    if explicit.is_none()
        && sway_socket.as_deref().is_none_or(str::is_empty)
        && i3_socket.as_deref().is_none_or(str::is_empty)
    {
        return Err(WminatorError::BackendUnavailable);
    }
    let mut connection = Connection::new()
        .await
        .map_err(|error| WminatorError::Connection {
            backend: explicit.map_or_else(
                || "i3/Sway".to_owned(),
                |backend| backend_name(backend).to_owned(),
            ),
            message: error.to_string(),
        })?;
    let version_human = if explicit.is_none()
        && sway_socket.as_deref().is_none_or(str::is_empty)
        && i3_socket
            .as_deref()
            .is_some_and(|socket| !socket.is_empty())
    {
        Some(
            connection
                .get_version()
                .await
                .map_err(|error| WminatorError::Connection {
                    backend: "i3/Sway".to_owned(),
                    message: error.to_string(),
                })?
                .human_readable,
        )
    } else {
        None
    };
    match selected_backend(
        explicit,
        sway_socket.as_deref(),
        i3_socket.as_deref(),
        version_human.as_deref(),
    )? {
        Backend::I3 => Ok(Box::new(I3Adapter { connection })),
        Backend::Sway => Ok(Box::new(SwayAdapter { connection })),
    }
}

macro_rules! impl_window_manager {
    ($adapter:ident, $backend:expr) => {
        #[async_trait(?Send)]
        impl WindowManager for $adapter {
            fn backend(&self) -> Backend {
                $backend
            }
            async fn command(&mut self, command: &str) -> Result<()> {
                run_command(&mut self.connection, command).await
            }
            async fn workspaces(&mut self) -> Result<Vec<WorkspaceSnapshot>> {
                snapshots(&mut self.connection).await
            }
            async fn focused_workspace(&mut self) -> Result<WorkspaceSnapshot> {
                snapshots(&mut self.connection)
                    .await?
                    .into_iter()
                    .find(|workspace| workspace.focused)
                    .ok_or(WminatorError::NoFocusedWorkspace)
            }
            async fn window_ids(&mut self) -> Result<HashSet<i64>> {
                tree_window_ids(&mut self.connection).await
            }
            async fn launch_and_wait(
                &mut self,
                launcher: &dyn ProcessLauncher,
                argv: &[String],
                rule: Option<&MatchRule>,
                timeout: f64,
            ) -> Result<WindowProperties> {
                launch_and_wait(
                    &mut self.connection,
                    $backend,
                    launcher,
                    argv,
                    rule,
                    timeout,
                )
                .await
            }
        }
    };
}
impl_window_manager!(I3Adapter, Backend::I3);
impl_window_manager!(SwayAdapter, Backend::Sway);

async fn run_command(connection: &mut Connection, command: &str) -> Result<()> {
    let outcomes = connection
        .run_command(command)
        .await
        .map_err(|error| WminatorError::Disconnected(error.to_string()))?;
    for outcome in outcomes {
        if let Err(error) = outcome {
            return Err(WminatorError::CommandRejected {
                command: command.to_owned(),
                reply: error.to_string(),
            });
        }
    }
    Ok(())
}

async fn snapshots(connection: &mut Connection) -> Result<Vec<WorkspaceSnapshot>> {
    let tree = connection
        .get_tree()
        .await
        .map_err(|error| WminatorError::Disconnected(error.to_string()))?;
    Ok(tree
        .iter()
        .filter(|node| node.node_type == NodeType::Workspace)
        .map(|node| WorkspaceSnapshot {
            number: node.num,
            name: node.name.clone().unwrap_or_default(),
            focused: node.iter().any(|child| child.focused),
            window_ids: node
                .iter()
                .filter(|child| is_window(child))
                .map(|child| child.id)
                .collect(),
        })
        .collect())
}

async fn tree_window_ids(connection: &mut Connection) -> Result<HashSet<i64>> {
    let tree = connection
        .get_tree()
        .await
        .map_err(|error| WminatorError::Disconnected(error.to_string()))?;
    Ok(tree
        .iter()
        .filter(|node| is_window(node))
        .map(|node| node.id)
        .collect())
}

fn is_window(node: &Node) -> bool {
    node.window.is_some() || node.app_id.is_some()
}

async fn launch_and_wait(
    connection: &mut Connection,
    backend: Backend,
    launcher: &dyn ProcessLauncher,
    argv: &[String],
    rule: Option<&MatchRule>,
    timeout: f64,
) -> Result<WindowProperties> {
    if backend == Backend::I3 && rule.is_some_and(|rule| rule.app_id.is_some()) {
        return Err(WminatorError::UnsupportedAppId);
    }
    if !timeout.is_finite() || timeout <= 0.0 {
        return Err(WminatorError::InvalidConfig {
            path: "<config>".into(),
            message: "window timeout must be positive and finite".to_owned(),
        });
    }
    let event_connection = Connection::new()
        .await
        .map_err(|error| WminatorError::Connection {
            backend: backend_name(backend).to_owned(),
            message: error.to_string(),
        })?;
    let mut events = event_connection
        .subscribe([EventType::Window])
        .await
        .map_err(|error| WminatorError::Connection {
            backend: backend_name(backend).to_owned(),
            message: error.to_string(),
        })?;
    // Establish the subscription before taking the baseline. A window arriving
    // in this interval is then both queued and excluded by ID, while a window
    // spawned immediately after `spawn_detached` cannot outrun the subscription.
    let baseline = tree_window_ids(connection).await?;
    launcher.spawn_detached(argv).await?;
    let deadline = tokio::time::Instant::now() + Duration::from_secs_f64(timeout);
    let found = loop {
        tokio::select! {
            event = events.next() => {
                match event {
                    Some(Ok(Event::Window(event))) if event.change == WindowChange::New && !baseline.contains(&event.container.id) => {
                        let candidate = properties(&event.container);
                        if let Some(candidate) = matching_new_window(candidate, &baseline, rule, backend)? { break Some(candidate); }
                    }
                    Some(Ok(_)) => {}
                    Some(Err(error)) => return Err(WminatorError::Disconnected(error.to_string())),
                    None => return Err(WminatorError::Disconnected("event stream ended".to_owned())),
                }
            }
            () = tokio::time::sleep(Duration::from_millis(50)) => {
                let tree = connection.get_tree().await.map_err(|error| WminatorError::Disconnected(error.to_string()))?;
                if let Some(candidate) = tree.iter().filter(|node| is_window(node)).map(properties).find_map(|candidate| matching_new_window(candidate, &baseline, rule, backend).transpose()).transpose()? { break Some(candidate); }
            }
            () = tokio::time::sleep_until(deadline) => break None,
        }
    };
    found.ok_or_else(|| WminatorError::LaunchTimeout {
        timeout,
        command: argv.join(" "),
    })
}

fn matching_new_window(
    candidate: WindowProperties,
    baseline: &HashSet<i64>,
    rule: Option<&MatchRule>,
    backend: Backend,
) -> Result<Option<WindowProperties>> {
    if baseline.contains(&candidate.id) {
        return Ok(None);
    }
    candidate
        .matches(rule, backend)
        .map(|matches| matches.then_some(candidate))
}

fn properties(node: &Node) -> WindowProperties {
    WindowProperties {
        id: node.id,
        class: node
            .window_properties
            .as_ref()
            .and_then(|value| value.class.clone()),
        title: node.name.clone().or_else(|| {
            node.window_properties
                .as_ref()
                .and_then(|value| value.title.clone())
        }),
        instance: node
            .window_properties
            .as_ref()
            .and_then(|value| value.instance.clone()),
        app_id: node.app_id.clone(),
    }
}

fn backend_name(backend: Backend) -> &'static str {
    match backend {
        Backend::I3 => "i3",
        Backend::Sway => "Sway",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fallback_considers_only_new_matching_ids() -> Result<()> {
        let baseline = HashSet::from([7]);
        let existing = WindowProperties {
            id: 7,
            title: Some("ready".to_owned()),
            ..WindowProperties::default()
        };
        let new = WindowProperties {
            id: 8,
            title: Some("READY now".to_owned()),
            ..WindowProperties::default()
        };
        let rule = MatchRule {
            title: Some("ready".to_owned()),
            ..MatchRule::default()
        };
        assert!(matching_new_window(existing, &baseline, Some(&rule), Backend::I3)?.is_none());
        assert_eq!(
            matching_new_window(new, &baseline, Some(&rule), Backend::I3)?.map(|window| window.id),
            Some(8)
        );
        Ok(())
    }
}
