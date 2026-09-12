//! loads topics from toml and validates them into the shape the site needs.
//!
//! two layouts are accepted side by side: a monolithic topics.toml whose
//! top level tables are each a topic, and topics/<slug>.toml files that each
//! hold a single topic and take their slug from the file name.

use std::collections::BTreeMap;
use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

pub const TOPICS_FILE: &str = "topics.toml";
pub const TOPICS_DIR: &str = "topics";

/// a score of -inf marks a requirement nobody has evaluated yet. any other
/// non finite score is treated the same way rather than poisoning the sums.
const UNEVALUATED: &str = "-inf";

#[derive(Deserialize)]
struct RawTopic {
    name: Option<String>,
    #[serde(default)]
    requirements: Vec<RawRequirement>,
    #[serde(default)]
    items: Vec<RawItem>,
}

#[derive(Deserialize)]
struct RawRequirement {
    name: String,
    priority: Option<i64>,
    #[serde(default)]
    force: bool,
}

#[derive(Deserialize)]
struct RawItem {
    name: String,
    #[serde(default)]
    skip: bool,
    #[serde(default)]
    evaluations: Vec<RawEvaluation>,
}

#[derive(Deserialize)]
struct RawEvaluation {
    name: String,
    score: f64,
    #[serde(default)]
    comment: String,
    #[serde(default)]
    sources: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct Topic {
    pub slug: String,
    pub name: String,
    pub requirements: Vec<Requirement>,
    pub items: Vec<Item>,
}

#[derive(Debug, Serialize)]
pub struct Requirement {
    pub name: String,
    /// ascending importance, negative for anti-requirements and absent for
    /// requirements the reader is expected to rank themselves.
    pub priority: Option<i64>,
    pub force: bool,
}

#[derive(Debug, Serialize)]
pub struct Item {
    pub name: String,
    /// one entry per requirement, in requirement order, so the browser can
    /// look an evaluation up by rank without carrying identifiers around.
    pub evaluations: Vec<Option<Evaluation>>,
}

#[derive(Debug, Serialize)]
pub struct Evaluation {
    pub score: f64,
    pub comment: String,
    /// where the score came from, in any form: a url, a page reference, a
    /// note on who measured it. free text, so a score can be traced back.
    pub sources: Vec<String>,
}

/// where a topic came from, which decides how the file is read and written.
#[derive(Clone, Copy, PartialEq)]
pub enum Layout {
    /// topics.toml, holding one table per topic
    Monolith,
    /// topics/<slug>.toml, the whole file being a single topic
    Single,
}

pub struct Source {
    pub path: PathBuf,
    pub layout: Layout,
}

/// every topic file below `root`, in a stable order.
pub fn sources(root: &Path) -> Result<Vec<Source>, String> {
    let mut sources = Vec::new();

    let monolith = root.join(TOPICS_FILE);
    if monolith.is_file() {
        sources.push(Source {
            path: monolith,
            layout: Layout::Monolith,
        });
    }
    for path in toml_files(&root.join(TOPICS_DIR))? {
        sources.push(Source {
            path,
            layout: Layout::Single,
        });
    }

    if sources.is_empty() {
        return Err(format!(
            "no topics found: expected {} or {}/*.toml under {}",
            TOPICS_FILE,
            TOPICS_DIR,
            root.display()
        ));
    }
    Ok(sources)
}

/// requirements rank by priority, ascending, with unranked ones last. the
/// formatter writes this order back to disk so a file reads in the order the
/// site ranks it.
pub fn priority_key(priority: Option<i64>) -> (bool, i64) {
    (priority.is_none(), priority.unwrap_or_default())
}

/// read every topic below `root`, ordered by display name.
pub fn load(root: &Path) -> Result<Vec<Topic>, String> {
    let mut raw: Vec<(String, RawTopic, PathBuf)> = Vec::new();

    for source in sources(root)? {
        match source.layout {
            Layout::Monolith => {
                let sections: BTreeMap<String, RawTopic> = parse(&source.path)?;
                raw.extend(
                    sections
                        .into_iter()
                        .map(|(slug, topic)| (slug, topic, source.path.clone())),
                );
            }
            Layout::Single => {
                let slug = slug_of(&source.path)?;
                raw.push((slug, parse(&source.path)?, source.path));
            }
        }
    }

    if raw.is_empty() {
        return Err("no topics found: every topic file was empty".to_string());
    }

    let mut seen: BTreeMap<String, PathBuf> = BTreeMap::new();
    let mut topics = Vec::new();
    for (slug, topic, path) in raw {
        if let Some(first) = seen.insert(slug.clone(), path.clone()) {
            return Err(format!(
                "topic {slug} is defined twice, in {} and {}",
                first.display(),
                path.display()
            ));
        }
        topics.push(convert(slug, topic).map_err(|e| format!("{}: {e}", path.display()))?);
    }

    topics.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(topics)
}

fn parse<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    toml::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

/// a per-file topic takes its slug from the file name.
fn slug_of(path: &Path) -> Result<String, String> {
    path.file_stem()
        .and_then(|stem| stem.to_str())
        .map(str::to_string)
        .ok_or_else(|| format!("{}: unreadable file name", path.display()))
}

/// the toml files directly inside `dir`, sorted so builds are reproducible.
fn toml_files(dir: &Path) -> Result<Vec<PathBuf>, String> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut paths = Vec::new();
    for entry in fs::read_dir(dir).map_err(|e| format!("{}: {e}", dir.display()))? {
        let path = entry.map_err(|e| format!("{}: {e}", dir.display()))?.path();
        if path.extension().is_some_and(|ext| ext == "toml") {
            paths.push(path);
        }
    }
    paths.sort();
    Ok(paths)
}

/// order the requirements and align every item's evaluations with them.
fn convert(slug: String, raw: RawTopic) -> Result<Topic, String> {
    let name = raw.name.unwrap_or_else(|| slug.clone());

    let mut requirements: Vec<Requirement> = raw
        .requirements
        .into_iter()
        .map(|r| Requirement {
            name: r.name,
            priority: r.priority,
            force: r.force,
        })
        .collect();
    requirements.sort_by_key(|r| priority_key(r.priority));

    let mut rank = BTreeMap::new();
    for (index, requirement) in requirements.iter().enumerate() {
        if rank.insert(requirement.name.clone(), index).is_some() {
            return Err(format!(
                "topic {slug} declares requirement {} twice",
                requirement.name
            ));
        }
    }

    let mut names = HashSet::new();
    let mut items = Vec::new();
    for item in raw.items.into_iter().filter(|item| !item.skip) {
        if !names.insert(item.name.clone()) {
            return Err(format!("topic {slug} declares item {} twice", item.name));
        }
        items.push(align(&slug, item, &rank, requirements.len())?);
    }

    Ok(Topic {
        slug,
        name,
        requirements,
        items,
    })
}

/// place an item's evaluations at the rank of the requirement they score.
fn align(
    slug: &str,
    item: RawItem,
    rank: &BTreeMap<String, usize>,
    total: usize,
) -> Result<Item, String> {
    let mut evaluations: Vec<Option<Evaluation>> = (0..total).map(|_| None).collect();
    for evaluation in item.evaluations {
        let index = *rank.get(&evaluation.name).ok_or_else(|| {
            format!(
                "topic {slug} item {} scores {}, which is not one of its requirements",
                item.name, evaluation.name
            )
        })?;
        if !evaluation.score.is_finite() {
            continue;
        }
        if evaluations[index].is_some() {
            return Err(format!(
                "topic {slug} item {} scores {} twice, use {UNEVALUATED} to leave it unknown",
                item.name, evaluation.name
            ));
        }
        evaluations[index] = Some(Evaluation {
            score: evaluation.score,
            comment: evaluation.comment,
            sources: evaluation.sources,
        });
    }
    Ok(Item {
        name: item.name,
        evaluations,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn topic(text: &str) -> Result<Topic, String> {
        let raw: RawTopic = toml::from_str(text).map_err(|e| e.to_string())?;
        convert("test".to_string(), raw)
    }

    #[test]
    fn requirements_are_ordered_by_priority_with_unranked_last() {
        let parsed = topic(
            r#"
            requirements = [
                { name = "unranked" },
                { name = "third", priority = 20 },
                { name = "first", priority = -10 },
                { name = "second", priority = 10 },
            ]
            "#,
        )
        .unwrap();
        let order: Vec<&str> = parsed
            .requirements
            .iter()
            .map(|r| r.name.as_str())
            .collect();
        assert_eq!(order, ["first", "second", "third", "unranked"]);
    }

    #[test]
    fn evaluations_line_up_with_requirement_order() {
        let parsed = topic(
            r#"
            requirements = [
                { name = "b", priority = 20 },
                { name = "a", priority = 10 },
            ]
            items = [
                { name = "only", evaluations = [ { name = "b", score = 0.5, comment = "hi" } ] },
            ]
            "#,
        )
        .unwrap();
        let evaluations = &parsed.items[0].evaluations;
        assert!(evaluations[0].is_none());
        assert_eq!(evaluations[1].as_ref().unwrap().score, 0.5);
        assert_eq!(evaluations[1].as_ref().unwrap().comment, "hi");
    }

    #[test]
    fn sources_travel_with_the_score_they_cite() {
        let parsed = topic(
            r#"
            requirements = [ { name = "a", priority = 10 } ]
            items = [
                { name = "cited", evaluations = [
                    { name = "a", score = 1.0, sources = ["https://example.com", "asked around"] },
                ] },
                { name = "uncited", evaluations = [ { name = "a", score = 1.0 } ] },
            ]
            "#,
        )
        .unwrap();
        let sources = |index: usize| parsed.items[index].evaluations[0].as_ref().unwrap();
        assert_eq!(sources(0).sources, ["https://example.com", "asked around"]);
        assert!(sources(1).sources.is_empty());
    }

    #[test]
    fn negative_infinity_reads_as_unevaluated() {
        let parsed = topic(
            r#"
            requirements = [ { name = "a", priority = 10 } ]
            items = [
                { name = "only", evaluations = [ { name = "a", score = -inf, comment = "" } ] },
            ]
            "#,
        )
        .unwrap();
        assert!(parsed.items[0].evaluations[0].is_none());
    }

    #[test]
    fn skipped_items_are_dropped() {
        let parsed = topic(
            r#"
            requirements = [ { name = "a", priority = 10 } ]
            items = [
                { name = "template", skip = true },
                { name = "real" },
            ]
            "#,
        )
        .unwrap();
        assert_eq!(parsed.items.len(), 1);
        assert_eq!(parsed.items[0].name, "real");
    }

    #[test]
    fn unknown_requirement_names_are_rejected() {
        let error = topic(
            r#"
            requirements = [ { name = "a", priority = 10 } ]
            items = [
                { name = "only", evaluations = [ { name = "typo", score = 1.0, comment = "" } ] },
            ]
            "#,
        )
        .unwrap_err();
        assert!(error.contains("typo"), "{error}");
    }

    #[test]
    fn duplicate_requirements_are_rejected() {
        let error = topic(
            r#"
            requirements = [
                { name = "a", priority = 10 },
                { name = "a", priority = 20 },
            ]
            "#,
        )
        .unwrap_err();
        assert!(error.contains("twice"), "{error}");
    }

    #[test]
    fn a_missing_name_falls_back_to_the_slug() {
        let parsed = topic("requirements = []").unwrap();
        assert_eq!(parsed.name, "test");
    }
}
