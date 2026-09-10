# DECIDE

decide helps you choose between things by ranking what you care about,
rather than arguing about a single overall score.

you write down the candidate items and how well each one meets each
requirement. decide publishes a static site where a reader drags those
requirements into their own order, and every item is rescored and resorted
in the browser as they do it. two people with the same data and different
priorities get different answers, which is the point.

## using the site

each topic page has four columns:

- **requirements** - things you want, most important at the top
- **non-requirements** - things you do not care about either way
- **anti-requirements** - things you actively want to avoid
- **suggested items** - the candidates, best match first

drag a requirement by its handle to reorder it or to move it between the
first three columns. press an item to see the score behind every
requirement, along with any comment explaining it.

the bookmark toggle on a requirement insists on it: items that do not fully
meet a forced requirement are struck through and pushed down the list.

the same explanation is a click away on the site itself, behind the **?** in
the top right of every page.

## writing topics

a topic is a TOML table with `requirements` and `items`. give it a file in
`topics/`, where the file name is the slug and the keys sit at the top
level:

```toml
# topics/fruit.toml

name = "Fruit"

requirements = [
	{ name = "Sweet", priority = 10 },
	{ name = "Cheap", priority = 20 },
	{ name = "Seasonal" },
	{ name = "Sour", priority = -10 },
]

items = [
	{ name = "Apple", evaluations = [
		{ name = "Sweet", score = 1.0, comment = "very sweet" },
		{ name = "Cheap", score = 0.5, comment = "" },
		{ name = "Sour", score = 0.0, comment = "" },
	]},
]
```

topics can also be collected into a single `topics.toml`, one table per
topic, named for its slug:

```toml
[fruit]

name = "Fruit"

requirements = [ ... ]
items = [ ... ]
```

both layouts can be used side by side. a slug may only be defined once.

### fields

| field | meaning |
| --- | --- |
| `name` | display name, defaulting to the slug |
| `requirements[].name` | unique within the topic, referenced by evaluations |
| `requirements[].priority` | starting rank, ascending. negative starts the requirement in the anti-requirements column, absent starts it in non-requirements |
| `requirements[].force` | start with the requirement forced on |
| `items[].name` | unique within the topic |
| `items[].skip` | leave the item out of the site, for templates and drafts |
| `items[].evaluations[].name` | must match a requirement of the same topic |
| `items[].evaluations[].score` | 0.0 to 1.0, how well the item meets that requirement. use `-inf` for not yet evaluated |
| `items[].evaluations[].comment` | shown when a reader expands the item |

`decide check` validates all of this without writing anything, and names the
file and topic behind any problem.

### filling in the gaps

writing `-inf` by hand for every requirement an item has not been scored
against gets old quickly. `decide fmt` does it for you:

```
$ decide fmt
topics/home-base.toml: filled in 38 unevaluated, reordered
topics/dweb-social.toml: unchanged
```

it gives every item an entry for every requirement, puts requirements in
the order the site ranks them, sorts items by name with `skip` templates
first, and lines each item's evaluations up with the requirements. comments
and existing formatting are preserved, and running it twice changes
nothing.

it also renumbers `priority` in steps of 5, so there is room to drop a new
requirement between two neighbours without renumbering the rest by hand.
requirements that shared a priority are separated in the order the file
already had them, and anti-requirements stay negative so they keep their
column. `decide fmt --check` writes nothing and exits non-zero if any file
is out of shape, which is what CI runs.

if you rename or delete a requirement, the evaluations that referred to it
are orphaned. `fmt` refuses to touch the file and names them, because those
entries hold scores and comments you wrote:

```
$ decide fmt
decide: topics/fruit.toml: item Apple scores Sweet, which no requirement
declares. rename the requirement back, or rerun with --prune to drop the scores
```

## building

install the pinned toolchain, then build:

```
$ mise install

$ make
```

`make` bundles the browser code, compiles the generator, and writes the site
to `site/`. to look at it locally:

```
$ make serve
```

the site is entirely static and every URL inside it is relative, so it works
unchanged at the root of a domain, under a subdirectory such as
`https://khimaros.github.io/decide/`, or straight off a local disk.

## publishing to github pages

[.github/workflows/pages.yml](.github/workflows/pages.yml) tests and
publishes the site on every push to the default branch. pull requests build
it too, but stop short of deploying.

turn it on once, in the repository settings under **pages**, by setting
**source** to **github actions**. the site then appears at
`https://<user>.github.io/<repo>/`, or at the root of the domain if the
repository is named `<user>.github.io`. both work without configuration
because every URL the generator writes is relative.

to publish by hand instead, `site/` is a complete upload on its own:

```
$ make

$ git subtree push --prefix site origin gh-pages
```

the generator writes a `.nojekyll` marker either way, so pages serves the
directory as is rather than running jekyll over it.

## development

| command | what it does |
| --- | --- |
| `make` | build the site into `site/` |
| `make check` | validate the topics, and that they are canonical, writing nothing |
| `make fmt` | sort the topic files and fill in unevaluated requirements |
| `make serve` | build, then serve `site/` on port 8080 |
| `make test` | rust unit tests and typescript type checking |
| `make test-e2e` | build a site from fixtures and drive it in a browser |
| `make precommit` | everything above plus `cargo fmt` and `clippy` |
| `make clean` | remove build output |

see [DESIGN.md](DESIGN.md) for how the pieces fit together and
[ROADMAP.md](ROADMAP.md) for what is planned.
