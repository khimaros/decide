# DESIGN

## shape

decide is a build tool and a page, with nothing in between. the published
site is a directory of files, with no server or database behind it.

```
topics.toml            src/topics.rs        templates/*.html      site/
topics/*.toml   ---->  load and validate  ---->  render  ---->  index.html
                                                                topics/<slug>/index.html
                                                                topics/<slug>/topic.json
web/src/*.ts    ---->  esbuild bundle     ---->  copy    ---->  static/decide.js
web/src/*.css                                                   static/decide.css
```

the generator runs once at build time and decides nothing about the answer.
every judgement a reader makes happens in the browser afterwards, against
data the page already has.

## the generator

`src/topics.rs` turns TOML into the one shape the rest of the program uses.
it resolves both source layouts, orders each topic's requirements by
priority, and rewrites every evaluation from a name into a position in that
order. anything that cannot be resolved is an error naming the file and the
topic, so a typo fails the build rather than silently scoring zero.

`src/render.rs` writes the site. it never erases a directory it did not
create: a non-empty output directory without a `.nojekyll` marker is left
alone.

`src/format.rs` is the only part that writes back to the sources. it edits
through `toml_edit` rather than reserialising, so lines nobody touched keep
their exact bytes, comments included. it shares `topics::priority_key` with
the loader, so the order it writes to disk is the order the site ranks by.
orphaned evaluations are refused rather than deleted, because they hold
scores and hand-written comments that a renamed requirement should not
quietly discard.

it also counts the scores that cite no source and warns about them on every
run. that count is the one thing in the file the formatter deliberately will
not fix: it can write a missing entry, but finding a source is research, not
formatting. so it is a warning rather than an error, and `--check` still
exits zero on it, which keeps CI honest about canonical shape without
blocking on a backlog of citations.

## the page

a topic's data is published beside its page as `topic.json`, and the page
names it in a `<meta name="topic-data">`. because the two sit in the same
directory, that name needs no prefix and no absolute URL, so it keeps
working wherever the site is served from. keeping the data out of the HTML
also lets a reader, or anything else, consume a topic directly.

every colour is a custom property, so following the system theme is one
`prefers-color-scheme` block that redefines the palette and nothing else.
the split between `--brand` and `--accent` exists because the brand colour
is legible behind white text but too dark to draw as a foreground on a dark
surface, and the same applies to `--badge-bg` against `--muted`.

the four sections are laid out by a multi-column container rather than by
flex rows. in rows, a short section leaves a gap as tall as the tallest
section beside it, because the next row cannot start until the tallest one
ends. columns let each section rise to meet the one above it. the column
count is capped at `--columns`, since column balancing packs cards into as
few columns as their tallest member allows and would otherwise leave a
trailing column empty on a wide screen.

balancing is also why a drag has to reserve space. a container that repacks
on any height change will happily move a section to another column while the
pointer is still down, and the row leaving one list and arriving in another
is exactly such a change. so as a drag begins every list grows by the height
of the row in flight: the list it left keeps its height, the list it lands in
already had the room, and no card resizes in between. the reserved strip is
drawn dashed, so the space doubles as the invitation to drop.

`web/src/score.ts` is pure: items in, ranked items out. `web/src/main.ts`
owns the DOM, and treats the DOM as the single source of truth for the
current ranking. reordering a list triggers a rescore that reads the lists
back, instead of keeping a parallel array in step by hand, which is where
the earlier implementation's ordering bugs came from.

## why evaluations are positional

an item's `evaluations` array runs parallel to the topic's `requirements`,
with `null` where nothing is known. the alternative, keying by requirement
name or by a synthetic id, costs a lookup table in the page and repeats
every requirement name once per item. positions are assigned by the
generator, which also owns the requirement order, so the two cannot drift.

## why a source is free text

an evaluation's `sources` are the references behind its score, and they are
plain strings because that is what a reference actually looks like: a URL
for some, a page number, a model name, or who measured it for others.
constraining the field to URLs would leave the rest uncited.

the page decides what to do with each one at draw time. a source parses as
an `http` or `https` URL becomes a link named for its host; everything else
is drawn as text. that check is what keeps a `javascript:` source, or any
other scheme, from becoming something a reader can click, and it is a
property the end to end tests assert directly against the rendered DOM.

## why every URL is relative

a project page lives under `https://<user>.github.io/<repo>/`, so a root
absolute URL like `/static/decide.css` points outside the site. pages are
written at a known depth, and templates prefix their links with a `base`
the generator supplies: empty for the index, `../../` for a topic. the end
to end tests serve the site from a subdirectory specifically so anything
that regresses to a root absolute URL fails.

that `base` is passed as a safe string. it is a constant the generator
chose rather than topic data, so escaping it would emit `..&#x2f;..&#x2f;`,
which browsers decode correctly but which is noise in the output. anything
that comes from a topic is still escaped normally.

## scoring

the requirement at the top of the list is worth `TOP_WEIGHT`, the next
`TOP_WEIGHT / 2`, the third `TOP_WEIGHT / 3`, and so on, so relative order
matters more than how many requirements there are. an anti-requirement
scores the same way and subtracts.

forcing a requirement marks any item that does not fully meet it as
filtered, and subtracts the requirement's full weight instead of adding a
partial one. a forced anti-requirement doubles its weight against anything
that has it. filtered items are struck through rather than hidden, because
knowing what got ruled out is part of the answer.

## testing

rust unit tests cover loading and validation, where the failure modes are
about bad input. everything else is tested end to end from `e2e/`: the site
is generated from fixtures in `e2e/testdata/`, served from a subdirectory,
and driven in headless chrome. those tests assert scores worked out by hand
from the weights above, so a change in scoring has to be deliberate.
