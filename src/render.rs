//! renders topics into a self contained static site.

use std::fs;
use std::path::Path;

use minijinja::context;
use minijinja::Environment;
use serde::Serialize;

use crate::topics::Topic;

/// github pages runs jekyll over an upload unless this marker is present.
/// it doubles as proof that a directory is ours before we erase it.
pub const MARKER_FILE: &str = ".nojekyll";

const INDEX_TEMPLATE: &str = "index.html";
const TOPIC_TEMPLATE: &str = "topic.html";
const INDEX_FILE: &str = "index.html";
const TOPICS_DIR: &str = "topics";
const STATIC_DIR: &str = "static";

/// a topic's data sits beside its page, so the page refers to it by name
/// alone and stays independent of where the site is served from.
const DATA_FILE: &str = "topic.json";

/// how many items a topic card previews on the index page.
const PREVIEW_ITEMS: usize = 5;

/// pages reach their assets through a relative prefix so the site can be
/// served from any path, eg. https://khimaros.github.io/decide/.
const INDEX_BASE: &str = "";
const TOPIC_BASE: &str = "../../";

/// a topic as it appears on the index page.
#[derive(Serialize)]
struct TopicCard<'a> {
    slug: &'a str,
    name: &'a str,
    items: Vec<&'a str>,
    item_count: usize,
    requirement_count: usize,
}

impl<'a> TopicCard<'a> {
    fn new(topic: &'a Topic) -> Self {
        TopicCard {
            slug: &topic.slug,
            name: &topic.name,
            items: topic
                .items
                .iter()
                .take(PREVIEW_ITEMS)
                .map(|i| i.name.as_str())
                .collect(),
            item_count: topic.items.len(),
            requirement_count: topic.requirements.len(),
        }
    }
}

/// write the whole site: an index, a page per topic, and the shared assets.
pub fn build(
    topics: &[Topic],
    templates: &Path,
    assets: &Path,
    output: &Path,
) -> Result<(), String> {
    let mut env = Environment::new();
    env.set_loader(minijinja::path_loader(templates));

    prepare(output)?;

    let cards: Vec<TopicCard> = topics.iter().map(TopicCard::new).collect();
    let index = render(
        &env,
        INDEX_TEMPLATE,
        context! { base => base(INDEX_BASE), topics => cards },
    )?;
    write(&output.join(INDEX_FILE), &index)?;

    for topic in topics {
        let dir = output.join(TOPICS_DIR).join(&topic.slug);
        let page = render(
            &env,
            TOPIC_TEMPLATE,
            context! { base => base(TOPIC_BASE), topic => topic, data => DATA_FILE },
        )?;
        write(&dir.join(INDEX_FILE), &page)?;
        write(&dir.join(DATA_FILE), &serialise(topic)?)?;
    }

    copy_tree(assets, &output.join(STATIC_DIR))
}

/// the relative prefix a page prepends to shared urls. it is ours rather
/// than a topic's, so it goes in untouched instead of being html escaped
/// into `..&#x2f;..&#x2f;`.
fn base(prefix: &str) -> minijinja::Value {
    minijinja::Value::from_safe_string(prefix.to_string())
}

fn render(env: &Environment, name: &str, ctx: minijinja::Value) -> Result<String, String> {
    env.get_template(name)
        .and_then(|template| template.render(ctx))
        .map_err(|e| format!("{name}: {e}"))
}

fn serialise(topic: &Topic) -> Result<String, String> {
    serde_json::to_string(topic).map_err(|e| format!("{}: {e}", topic.slug))
}

/// start from an empty directory, refusing to erase anything we did not
/// generate ourselves.
fn prepare(output: &Path) -> Result<(), String> {
    if output.is_dir() && !is_empty(output)? {
        if !output.join(MARKER_FILE).exists() {
            return Err(format!(
                "refusing to overwrite {}: not a generated site",
                output.display()
            ));
        }
        fs::remove_dir_all(output).map_err(|e| format!("{}: {e}", output.display()))?;
    }
    write(&output.join(MARKER_FILE), "")
}

fn is_empty(dir: &Path) -> Result<bool, String> {
    let mut entries = fs::read_dir(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    Ok(entries.next().is_none())
}

fn write(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("{}: {e}", parent.display()))?;
    }
    fs::write(path, content).map_err(|e| format!("{}: {e}", path.display()))
}

fn copy_tree(source: &Path, dest: &Path) -> Result<(), String> {
    if !source.is_dir() {
        return Err(format!(
            "{}: missing assets, run `make assets` first",
            source.display()
        ));
    }
    fs::create_dir_all(dest).map_err(|e| format!("{}: {e}", dest.display()))?;
    for entry in fs::read_dir(source).map_err(|e| format!("{}: {e}", source.display()))? {
        let entry = entry.map_err(|e| format!("{}: {e}", source.display()))?;
        let target = dest.join(entry.file_name());
        if entry.path().is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), &target).map_err(|e| format!("{}: {e}", target.display()))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::topics;

    #[test]
    fn a_relative_base_is_not_html_escaped() {
        let mut env = Environment::new();
        env.add_template(
            "t.html",
            r#"<script src="{{ base }}static/decide.js"></script>"#,
        )
        .unwrap();
        let out = env
            .get_template("t.html")
            .unwrap()
            .render(context! { base => base(TOPIC_BASE) })
            .unwrap();
        assert_eq!(out, r#"<script src="../../static/decide.js"></script>"#);
    }

    #[test]
    fn a_topic_name_is_still_html_escaped() {
        let mut env = Environment::new();
        env.add_template("t.html", "<title>{{ name }}</title>")
            .unwrap();
        let out = env
            .get_template("t.html")
            .unwrap()
            .render(context! { name => "</title><script>alert(1)" })
            .unwrap();
        assert!(!out.contains("<script>"), "{out}");
    }

    #[test]
    fn a_foreign_directory_is_left_alone() {
        let dir = std::env::temp_dir().join("decide-render-guard");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("precious.txt"), "keep me").unwrap();
        let error = prepare(&dir).unwrap_err();
        assert!(error.contains("refusing"), "{error}");
        assert!(dir.join("precious.txt").exists());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_generated_directory_is_replaced() {
        let dir = std::env::temp_dir().join("decide-render-replace");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(MARKER_FILE), "").unwrap();
        fs::write(dir.join("stale.html"), "old").unwrap();
        prepare(&dir).unwrap();
        assert!(!dir.join("stale.html").exists());
        assert!(dir.join(MARKER_FILE).exists());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn cards_preview_a_bounded_number_of_items() {
        let text = (0..PREVIEW_ITEMS + 3)
            .map(|i| format!("{{ name = \"item{i}\" }},"))
            .collect::<Vec<_>>()
            .join("\n");
        let dir = std::env::temp_dir().join("decide-render-cards");
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("topics.toml"),
            format!("[t]\nitems = [\n{text}\n]\n"),
        )
        .unwrap();
        let loaded = topics::load(&dir).unwrap();
        let card = TopicCard::new(&loaded[0]);
        assert_eq!(card.items.len(), PREVIEW_ITEMS);
        assert_eq!(card.item_count, PREVIEW_ITEMS + 3);
        fs::remove_dir_all(&dir).unwrap();
    }
}
