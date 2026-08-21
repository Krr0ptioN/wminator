#![forbid(unsafe_code)]

use anyhow::Context;
use clap::{Parser, Subcommand};
use tracing_subscriber::EnvFilter;
use wminator::{
    adapters::{OsEditor, OsProcessLauncher, RofiSelector, YamlConfigRepository, connect},
    application,
    domain::Backend,
    ports::ConfigRepository,
};

#[derive(Debug, Parser)]
#[command(
    name = "wminator",
    version,
    about = "Declarative i3 and Sway workspace layout manager"
)]
struct Cli {
    #[arg(short, long, global = true, help = "Enable debug logging")]
    verbose: bool,
    #[arg(
        long,
        global = true,
        value_enum,
        help = "Select the window-manager backend"
    )]
    backend: Option<Backend>,
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    #[command(about = "Open a layout by name or path")]
    Open {
        name: String,
        #[arg(short, long)]
        force: bool,
    },
    #[command(about = "List available layout configs")]
    List,
    #[command(about = "Create a new layout config")]
    Create { name: String },
    #[command(about = "Edit a layout config in $EDITOR")]
    Edit { name: String },
    #[command(about = "Validate a layout config")]
    Validate { name: String },
    #[command(about = "Select and open a layout with Rofi")]
    Rofi {
        #[arg(long, default_value = "wminator:")]
        prompt: String,
        #[arg(long, default_value = "vercel-premium")]
        theme: String,
        #[arg(short, long)]
        force: bool,
    },
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let filter = if cli.verbose {
        EnvFilter::new("debug")
    } else {
        EnvFilter::new("info")
    };
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .without_time()
        .init();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("failed to create Tokio runtime")?;
    runtime.block_on(run(cli))
}

async fn run(cli: Cli) -> anyhow::Result<()> {
    let repository = YamlConfigRepository::from_environment();
    match cli.command {
        Commands::List => {
            let layouts = repository.list()?;
            if layouts.is_empty() {
                println!("No layouts found.");
            } else {
                println!("{}", layouts.join("\n"));
            }
        }
        Commands::Create { name } => println!(
            "created {}",
            application::create(&repository, &name)?.display()
        ),
        Commands::Edit { name } => {
            let (path, created) = application::edit(&repository, &OsEditor, &name)?;
            if created {
                println!("created {}", path.display());
            }
        }
        Commands::Validate { name } => {
            application::load_layout(&repository, &name)?;
            println!("'{name}' is valid");
        }
        Commands::Open { name, force } => {
            open_named(&repository, cli.backend, &name, force).await?
        }
        Commands::Rofi {
            prompt,
            theme,
            force,
        } => {
            if let Some(name) = application::rofi(&repository, &RofiSelector, &prompt, &theme)? {
                open_named(&repository, cli.backend, &name, force).await?;
            }
        }
    }
    Ok(())
}

async fn open_named(
    repository: &dyn ConfigRepository,
    backend: Option<Backend>,
    name: &str,
    force: bool,
) -> anyhow::Result<()> {
    let config = application::load_layout(repository, name)?;
    let mut wm = connect(backend).await?;
    application::open(wm.as_mut(), &OsProcessLauncher, &config, force).await?;
    println!("layout '{}' applied", config.name);
    Ok(())
}
