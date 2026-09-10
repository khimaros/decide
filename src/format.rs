//! rewrites topic files into a canonical shape: requirements in the order the
//! site ranks them, items by name, and an explicit unevaluated entry for every
//! requirement nobody has scored yet.
//!
//! edits are made through toml_edit, so lines nobody touched keep their exact
//! formatting and comments.

use std::collections::HashMap;
use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use toml_edit::Array;
use toml_edit::DocumentMut;
use toml_edit::InlineTable;
use toml_edit::Table;
use toml_edit::Value;

use crate::topics;
use crate::topics::Layout;

const REQUIREMENTS: &str = "requirements";
const ITEMS: &str = "items";
const EVALUATIONS: &str = "evaluations";
const NAME: &str = "name";
const PRIORITY: &str = "priority";
const SKIP: &str = "skip";

/// indentation for entries added to an array that has none to copy.
const NESTED_INDENT: &str = "\n\t\t";

/// what an unscored requirement looks like once written down.
const UNEVALUATED: &str = "-inf";

/// gap left between renumbered priorities.
const PRIORITY_STEP: i64 = 5;

pub struct Options {
    /// report what would change instead of writing it
    pub check: bool,
    /// drop evaluations whose requirement no longer exists
    pub prune: bool,
}

#[derive(Debug, Default)]
pub struct Report {
    pub path: PathBuf,
    pub added: usize,
    pub pruned: usize,
    pub changed: bool,
}

/// bring every topic file below `root` into canonical shape.
pub fn format(root: &Path, options: &Options) -> Result<Vec<Report>, String> {
    topics::sources(root)?
        .iter()
        .map(|source| format_file(source, options))
        .collect()
}

fn format_file(source: &topics::Source, options: &Options) -> Result<Report, String> {
    let original =
        fs::read_to_string(&source.path).map_err(|e| format!("{}: {e}", source.path.display()))?;
    let mut doc: DocumentMut = original
        .parse()
        .map_err(|e| format!("{}: {e}", source.path.display()))?;

    let mut report = Report {
        path: source.path.clone(),
        ..Default::default()
    };
    let blame = |e| format!("{}: {e}", source.path.display());

    match source.layout {
        Layout::Monolith => {
            for (_, item) in doc.iter_mut() {
                if let Some(table) = item.as_table_mut() {
                    format_topic(table, options, &mut report).map_err(blame)?;
                }
            }
        }
        Layout::Single => format_topic(doc.as_table_mut(), options, &mut report).map_err(blame)?,
    }

    let updated = doc.to_string();
    report.changed = updated != original;
    if report.changed && !options.check {
        fs::write(&source.path, updated).map_err(|e| format!("{}: {e}", source.path.display()))?;
    }
    Ok(report)
}

fn format_topic(topic: &mut Table, options: &Options, report: &mut Report) -> Result<(), String> {
    let names = order_requirements(topic);
    order_items(topic);

    let Some(items) = array_mut(topic, ITEMS) else {
        return Ok(());
    };
    for value in items.iter_mut() {
        let Some(item) = value.as_inline_table_mut() else {
            continue;
        };
        if item.get(SKIP).and_then(Value::as_bool).unwrap_or(false) {
            continue;
        }
        fill_item(item, &names, options, report)?;
    }
    Ok(())
}

/// sort the requirements the way the site ranks them and report their names
/// in that order.
fn order_requirements(topic: &mut Table) -> Vec<String> {
    let Some(array) = array_mut(topic, REQUIREMENTS) else {
        return Vec::new();
    };
    sort_array(array, |value| {
        let priority = field(value, PRIORITY).and_then(Value::as_integer);
        topics::priority_key(priority)
    });
    renumber_priorities(array);
    array.iter().filter_map(entry_name).collect()
}

fn priority_of(value: &Value) -> Option<i64> {
    field(value, PRIORITY).and_then(Value::as_integer)
}

/// space the ranked requirements evenly in the order they now sit, so there is
/// room to drop something between two neighbours without renumbering by hand.
/// anti-requirements stay negative, or they would change column. ties broke in
/// file order during the sort above, and that order is what gets numbered.
fn renumber_priorities(array: &mut Array) {
    let negatives = array
        .iter()
        .filter(|value| priority_of(value).is_some_and(|priority| priority < 0))
        .count() as i64;

    let mut rank = 0;
    for value in array.iter_mut() {
        let Some(table) = value.as_inline_table_mut() else {
            continue;
        };
        if table.get(PRIORITY).and_then(Value::as_integer).is_none() {
            continue;
        }
        rank += 1;
        let spaced = if rank <= negatives {
            (rank - negatives - 1) * PRIORITY_STEP
        } else {
            (rank - negatives) * PRIORITY_STEP
        };
        let Some(priority) = table.get_mut(PRIORITY) else {
            continue;
        };
        // assign through the existing value so its spacing survives.
        let decor = priority.decor().clone();
        *priority = Value::from(spaced);
        *priority.decor_mut() = decor;
    }
}

/// templates first, so they stay easy to find, then everything by name.
fn order_items(topic: &mut Table) {
    let Some(array) = array_mut(topic, ITEMS) else {
        return;
    };
    sort_array(array, |value| {
        let skip = field(value, SKIP).and_then(Value::as_bool).unwrap_or(false);
        (!skip, entry_name(value).unwrap_or_default())
    });
}

/// give an item an entry for every requirement, in requirement order.
fn fill_item(
    item: &mut InlineTable,
    names: &[String],
    options: &Options,
    report: &mut Report,
) -> Result<(), String> {
    let label = item
        .get(NAME)
        .and_then(Value::as_str)
        .unwrap_or("<unnamed>")
        .to_string();
    let wanted: HashSet<&str> = names.iter().map(String::as_str).collect();
    let evaluations = evaluations_mut(item)?;

    let orphans: Vec<String> = evaluations
        .iter()
        .filter_map(entry_name)
        .filter(|name| !wanted.contains(name.as_str()))
        .collect();
    if !orphans.is_empty() {
        if !options.prune {
            return Err(format!(
                "item {label} scores {}, which no requirement declares. \
                 rename the requirement back, or rerun with --prune to drop the scores",
                orphans.join(", ")
            ));
        }
        evaluations
            .retain(|value| entry_name(value).is_some_and(|name| wanted.contains(name.as_str())));
        report.pruned += orphans.len();
    }

    let present: HashSet<String> = evaluations.iter().filter_map(entry_name).collect();
    let prefix = entry_prefix(evaluations);
    for name in names.iter().filter(|name| !present.contains(*name)) {
        let mut value = unevaluated(name)?;
        value.decor_mut().set_prefix(prefix.clone());
        evaluations.push_formatted(value);
        report.added += 1;
    }

    let rank: HashMap<&str, usize> = names.iter().map(String::as_str).zip(0..).collect();
    sort_array(evaluations, |value| {
        entry_name(value)
            .and_then(|name| rank.get(name.as_str()).copied())
            .unwrap_or(usize::MAX)
    });
    Ok(())
}

/// an entry for a requirement nobody has scored, written the way the topics
/// are written by hand.
fn unevaluated(name: &str) -> Result<Value, String> {
    let quoted = Value::from(name).to_string();
    let entry = format!(
        "{{ name = {}, score = {UNEVALUATED}, comment = \"\" }}",
        quoted.trim()
    );
    entry
        .parse::<Value>()
        .map_err(|e| format!("cannot write an entry for {name}: {e}"))
}

fn evaluations_mut(item: &mut InlineTable) -> Result<&mut Array, String> {
    if !item.contains_key(EVALUATIONS) {
        let mut array = Array::new();
        array.set_trailing(NESTED_INDENT);
        array.set_trailing_comma(true);
        item.insert(EVALUATIONS, Value::Array(array));
    }
    item.get_mut(EVALUATIONS)
        .and_then(|value| value.as_array_mut())
        .ok_or_else(|| format!("{EVALUATIONS} must be an array"))
}

/// reorder an array in place. each entry keeps its own decoration, so its
/// indentation and any comment above it travel with it.
fn sort_array<K: Ord>(array: &mut Array, key: impl Fn(&Value) -> K) {
    let mut values: Vec<Value> = array.iter().cloned().collect();
    values.sort_by_key(&key);

    let trailing = array.trailing().clone();
    let trailing_comma = array.trailing_comma();
    array.clear();
    for value in values {
        array.push_formatted(value);
    }
    array.set_trailing(trailing);
    array.set_trailing_comma(trailing_comma);
}

/// copy the indentation an array already uses so added entries match.
fn entry_prefix(array: &Array) -> String {
    array
        .iter()
        .next()
        .and_then(|value| value.decor().prefix())
        .and_then(|prefix| prefix.as_str())
        .unwrap_or(NESTED_INDENT)
        .to_string()
}

fn array_mut<'a>(table: &'a mut Table, key: &str) -> Option<&'a mut Array> {
    table.get_mut(key).and_then(|item| item.as_array_mut())
}

fn field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_inline_table()?.get(key)
}

fn entry_name(value: &Value) -> Option<String> {
    field(value, NAME)?.as_str().map(str::to_string)
}

#[cfg(test)]
mod tests {
    use super::*;

    const OPTIONS: Options = Options {
        check: false,
        prune: false,
    };

    fn run(text: &str, options: &Options) -> Result<(String, Report), String> {
        let mut doc: DocumentMut = text
            .parse()
            .map_err(|e: toml_edit::TomlError| e.to_string())?;
        let mut report = Report::default();
        format_topic(doc.as_table_mut(), options, &mut report)?;
        Ok((doc.to_string(), report))
    }

    #[test]
    fn missing_evaluations_are_filled_in_as_unevaluated() {
        let (out, report) = run(
            "requirements = [\n\t{ name = \"A\", priority = 10 },\n\t{ name = \"B\", priority = 20 },\n]\n\
             items = [\n\t{ name = \"one\", evaluations = [\n\t\t{ name = \"A\", score = 1.0, comment = \"\" },\n\t]},\n]\n",
            &OPTIONS,
        )
        .unwrap();
        assert_eq!(report.added, 1);
        assert!(
            out.contains("{ name = \"B\", score = -inf, comment = \"\" }"),
            "{out}"
        );
    }

    #[test]
    fn evaluations_follow_requirement_order() {
        let (out, _) = run(
            "requirements = [\n\t{ name = \"B\", priority = 20 },\n\t{ name = \"A\", priority = 10 },\n]\n\
             items = [\n\t{ name = \"one\", evaluations = [\n\t\t{ name = \"B\", score = 0.5, comment = \"\" },\n\t\t{ name = \"A\", score = 1.0, comment = \"\" },\n\t]},\n]\n",
            &OPTIONS,
        )
        .unwrap();
        assert!(
            out.find("\"A\", score").unwrap() < out.find("\"B\", score").unwrap(),
            "{out}"
        );
    }

    #[test]
    fn unranked_requirements_sort_last_like_the_site_ranks_them() {
        let (out, _) = run(
            "requirements = [\n\t{ name = \"none\" },\n\t{ name = \"zero\", priority = 0 },\n]\nitems = []\n",
            &OPTIONS,
        )
        .unwrap();
        assert!(
            out.find("\"zero\"").unwrap() < out.find("\"none\"").unwrap(),
            "{out}"
        );
    }

    #[test]
    fn orphaned_scores_are_kept_unless_pruning() {
        let text = "requirements = [\n\t{ name = \"A\", priority = 10 },\n]\n\
                    items = [\n\t{ name = \"one\", evaluations = [\n\t\t{ name = \"gone\", score = 1.0, comment = \"hours of work\" },\n\t]},\n]\n";
        let error = run(text, &OPTIONS).unwrap_err();
        assert!(error.contains("gone"), "{error}");
        assert!(error.contains("--prune"), "{error}");

        let (out, report) = run(
            text,
            &Options {
                check: false,
                prune: true,
            },
        )
        .unwrap();
        assert_eq!(report.pruned, 1);
        assert!(!out.contains("gone"), "{out}");
    }

    #[test]
    fn templates_stay_at_the_top_and_are_left_unfilled() {
        let (out, _) = run(
            "requirements = [\n\t{ name = \"A\", priority = 10 },\n]\n\
             items = [\n\t{ name = \"beta\" },\n\t{ name = \"template\", skip = true },\n]\n",
            &OPTIONS,
        )
        .unwrap();
        assert!(
            out.find("template").unwrap() < out.find("beta").unwrap(),
            "{out}"
        );
        assert!(!out.contains("skip = true, evaluations"), "{out}");
    }

    #[test]
    fn comments_and_untouched_lines_survive() {
        // priority 5 because the first ranked requirement is renumbered there.
        let text = "# how sweet it is\nrequirements = [\n\t{ name = \"A\", priority = 5 },\n]\n\
                    items = [\n\t{ name = \"one\", evaluations = [\n\t\t{ name = \"A\", score = 1.0, comment = \"kept\" },\n\t]},\n]\n";
        let (out, report) = run(text, &OPTIONS).unwrap();
        assert!(out.contains("# how sweet it is"), "{out}");
        assert_eq!(
            out, text,
            "an already canonical file should come back unchanged"
        );
        assert_eq!(report.added, 0);
    }

    #[test]
    fn formatting_is_idempotent() {
        let text = "requirements = [\n\t{ name = \"B\", priority = 20 },\n\t{ name = \"A\", priority = 10 },\n]\n\
                    items = [\n\t{ name = \"one\", evaluations = [\n\t\t{ name = \"B\", score = 0.5, comment = \"\" },\n\t]},\n]\n";
        let (once, _) = run(text, &OPTIONS).unwrap();
        let (twice, report) = run(&once, &OPTIONS).unwrap();
        assert_eq!(once, twice);
        assert_eq!(report.added, 0);
    }

    #[test]
    fn an_item_without_any_evaluations_gets_a_full_set() {
        let (out, report) = run(
            "requirements = [\n\t{ name = \"A\", priority = 10 },\n]\nitems = [\n\t{ name = \"one\" },\n]\n",
            &OPTIONS,
        )
        .unwrap();
        assert_eq!(report.added, 1);
        assert!(out.contains("name = \"A\", score = -inf"), "{out}");
    }
}
