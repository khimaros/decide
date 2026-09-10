//! decide renders comparison topics written in toml into a static site.

mod format;
mod render;
mod topics;

use std::path::PathBuf;
use std::process;

const USAGE: &str = "\
usage: decide <command> [options]

commands:
  build   render the static site
  check   load and validate the topics without writing anything
  fmt     sort the topic files and fill in unevaluated requirements

options:
  --data <dir>       holds topics.toml and topics/*.toml (default: .)
  --templates <dir>  page templates (default: templates)
  --assets <dir>     built web assets to publish (default: web/dist)
  --output <dir>     where to write the site (default: site)
  --check            fmt: report what would change, write nothing
  --prune            fmt: drop scores whose requirement no longer exists
  --help             show this message
";

struct Args {
    command: String,
    data: PathBuf,
    templates: PathBuf,
    assets: PathBuf,
    output: PathBuf,
    check: bool,
    prune: bool,
}

impl Default for Args {
    fn default() -> Self {
        Args {
            command: String::new(),
            data: PathBuf::from("."),
            templates: PathBuf::from("templates"),
            assets: PathBuf::from("web/dist"),
            output: PathBuf::from("site"),
            check: false,
            prune: false,
        }
    }
}

fn parse_args(argv: impl Iterator<Item = String>) -> Result<Args, String> {
    let mut args = Args::default();
    let mut rest = argv.peekable();

    while let Some(arg) = rest.next() {
        let mut value = || {
            rest.next()
                .ok_or_else(|| format!("{arg} needs a directory"))
        };
        match arg.as_str() {
            "--data" => args.data = value()?.into(),
            "--templates" => args.templates = value()?.into(),
            "--assets" => args.assets = value()?.into(),
            "--output" => args.output = value()?.into(),
            "--check" => args.check = true,
            "--prune" => args.prune = true,
            "--help" | "-h" => {
                print!("{USAGE}");
                process::exit(0);
            }
            _ if arg.starts_with('-') => return Err(format!("unknown option {arg}")),
            _ if args.command.is_empty() => args.command = arg,
            _ => return Err(format!("unexpected argument {arg}")),
        }
    }

    if args.command.is_empty() {
        return Err("no command given".to_string());
    }
    Ok(args)
}

/// rewrite the topic files, or report what needs rewriting. this runs before
/// anything is loaded, because filling in a file is how you fix the errors
/// loading would otherwise raise.
fn format_topics(args: &Args) -> Result<(), String> {
    let options = format::Options {
        check: args.check,
        prune: args.prune,
    };
    let reports = format::format(&args.data, &options)?;

    let mut stale = 0;
    for report in &reports {
        let path = report.path.display();
        if !report.changed {
            println!("{path}: unchanged");
            continue;
        }
        stale += 1;
        if args.check {
            println!("{path}: not canonical, run `decide fmt`");
            continue;
        }
        let mut changes = Vec::new();
        if report.added > 0 {
            changes.push(format!("filled in {} unevaluated", report.added));
        }
        if report.pruned > 0 {
            changes.push(format!("pruned {} orphaned", report.pruned));
        }
        changes.push("reordered".to_string());
        println!("{path}: {}", changes.join(", "));
    }

    if args.check && stale > 0 {
        return Err(format!("{stale} file(s) are not canonical"));
    }
    Ok(())
}

fn run(args: &Args) -> Result<(), String> {
    if args.command == "fmt" {
        return format_topics(args);
    }

    let topics = topics::load(&args.data)?;

    let items: usize = topics.iter().map(|t| t.items.len()).sum();
    let requirements: usize = topics.iter().map(|t| t.requirements.len()).sum();
    println!(
        "loaded {} topics, {items} items, {requirements} requirements",
        topics.len()
    );

    match args.command.as_str() {
        "check" => Ok(()),
        "build" => {
            render::build(&topics, &args.templates, &args.assets, &args.output)?;
            println!(
                "wrote {} pages to {}",
                topics.len() + 1,
                args.output.display()
            );
            Ok(())
        }
        other => Err(format!("unknown command {other}")),
    }
}

fn main() {
    let args = match parse_args(std::env::args().skip(1)) {
        Ok(args) => args,
        Err(error) => {
            eprintln!("decide: {error}\n\n{USAGE}");
            process::exit(2);
        }
    };

    if let Err(error) = run(&args) {
        eprintln!("decide: {error}");
        process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(argv: &[&str]) -> Result<Args, String> {
        parse_args(argv.iter().map(|s| s.to_string()))
    }

    #[test]
    fn defaults_apply_when_only_a_command_is_given() {
        let args = parse(&["build"]).unwrap();
        assert_eq!(args.command, "build");
        assert_eq!(args.output, PathBuf::from("site"));
        assert_eq!(args.data, PathBuf::from("."));
    }

    #[test]
    fn directories_can_be_overridden() {
        let args = parse(&["build", "--output", "/tmp/out", "--data", "/tmp/in"]).unwrap();
        assert_eq!(args.output, PathBuf::from("/tmp/out"));
        assert_eq!(args.data, PathBuf::from("/tmp/in"));
    }

    #[test]
    fn a_missing_command_is_an_error() {
        assert!(parse(&[]).is_err());
    }

    #[test]
    fn an_option_without_a_value_is_an_error() {
        assert!(parse(&["build", "--output"]).is_err());
    }

    #[test]
    fn unknown_options_are_rejected() {
        assert!(parse(&["build", "--nope"]).is_err());
    }
}
