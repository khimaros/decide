#!/usr/bin/env python3
""" end to end tests for the generated site. """

import json
import os
import re
import shutil
import tempfile
import tomllib
import unittest
import urllib.request
from urllib.parse import urljoin

from e2e import harness

# the site is generated into a subdirectory of the served root, so anything
# that assumes it lives at the root of a domain fails loudly here.
SITE_DIR = 'decide'

# scores the fixture topics must produce, worked out by hand from the
# weights in web/src/score.ts.
FRUIT_RANKING = [('Apple', 125, False), ('Mystery', 0, False), ('Lemon', -50, False)]
VEGGIE_RANKING = [('Carrot', 100, False), ('Spinach', -100, True)]


def fetch(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read()


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.output = os.path.join(cls.tmp.name, SITE_DIR)
        result = harness.build(cls.output)
        if result.returncode != 0:
            raise AssertionError('build failed:\n%s%s' % (result.stdout, result.stderr))
        cls.server = harness.WebServer(cls.tmp.name).__enter__()
        cls.base = urljoin(cls.server.url, SITE_DIR + '/')

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        cls.tmp.cleanup()

    def page(self, *parts):
        return os.path.join(self.output, *parts)

    def parsed(self, url):
        _, body = fetch(url)
        parser = harness.RefParser()
        parser.feed(body.decode('utf-8'))
        return parser

    def pages(self):
        return [self.base] + [
            urljoin(self.base, 'topics/%s/' % slug) for slug in ('fruit', 'veggie')
        ]

    def test_every_topic_gets_a_page_and_a_data_file(self):
        self.assertTrue(os.path.exists(self.page('index.html')))
        self.assertTrue(os.path.exists(self.page('.nojekyll')))
        for slug in ('fruit', 'veggie'):
            self.assertTrue(os.path.exists(self.page('topics', slug, 'index.html')), slug)
            self.assertTrue(os.path.exists(self.page('topics', slug, 'topic.json')), slug)
        for asset in ('decide.js', 'decide.css', 'logo.svg'):
            self.assertTrue(os.path.exists(self.page('static', asset)), asset)

    def test_a_page_names_a_data_file_beside_itself(self):
        for slug in ('fruit', 'veggie'):
            html = harness.read(self.page('topics', slug, 'index.html'))
            named = harness.data_file(html)
            self.assertNotIn('/', named, 'the data url should be relative to the page')
            status, body = fetch(urljoin(self.base, 'topics/%s/%s' % (slug, named)))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['slug'], slug)

    def test_urls_are_written_plainly(self):
        # base prefixes are ours, not topic data, so they must not arrive
        # html escaped as ..&#x2f;..&#x2f;
        for slug in ('fruit', 'veggie'):
            html = harness.read(self.page('topics', slug, 'index.html'))
            self.assertNotIn('&#x2f;', html)
            self.assertIn('src="../../static/decide.js"', html)

    def test_pages_have_no_root_absolute_urls(self):
        for url in self.pages():
            for ref in self.parsed(url).refs:
                self.assertFalse(ref.startswith('/'), '%s references %s' % (url, ref))

    def test_referenced_assets_resolve(self):
        for url in self.pages():
            refs = self.parsed(url).refs
            self.assertTrue(refs, 'no references on %s' % url)
            for ref in refs:
                target = urljoin(url, ref)
                self.assertTrue(target.startswith(self.base),
                                '%s escapes the site root via %s' % (url, ref))
                status, _ = fetch(target)
                self.assertEqual(status, 200, target)

    def test_index_links_to_every_topic_by_directory(self):
        # a directory, not its index.html: the server picks the index, and the
        # url a reader copies out of the bar stays the tidy one.
        refs = self.parsed(self.base).refs
        for slug in ('fruit', 'veggie'):
            self.assertIn('./topics/%s/' % slug, refs)
        self.assertNotIn('index.html', ' '.join(refs))

    def test_every_page_offers_help_on_how_to_read_it(self):
        for url in self.pages():
            _, body = fetch(url)
            html = body.decode('utf-8')
            self.assertIn('popovertarget="help"', html, url)
            self.assertIn('id="help"', html, url)
            self.assertIn('popover', html, url)

    def test_a_topic_file_supplies_its_own_slug_and_name(self):
        parser = self.parsed(urljoin(self.base, 'topics/veggie/'))
        self.assertEqual(parser.title, 'Decide - Vegetables')

    def test_published_data_matches_the_toml_source(self):
        with open(os.path.join(harness.TESTDATA, 'topics.toml'), 'rb') as f:
            source = tomllib.load(f)['fruit']
        topic = harness.load_json(self.page('topics', 'fruit', 'topic.json'))

        self.assertEqual(topic['name'], source['name'])
        self.assertEqual(
            [r['name'] for r in topic['requirements']],
            ['Sour', 'Sweet', 'Cheap', 'Seasonal'],
            'requirements should be ordered by priority with unranked last')

        wanted = [i['name'] for i in source['items'] if not i.get('skip')]
        self.assertEqual([i['name'] for i in topic['items']], wanted)

        rank = {r['name']: i for i, r in enumerate(topic['requirements'])}
        for item, raw in zip(topic['items'], source['items']):
            for evaluation in raw.get('evaluations', []):
                slot = item['evaluations'][rank[evaluation['name']]]
                if evaluation['score'] == float('-inf'):
                    self.assertIsNone(slot, '%s %s' % (item['name'], evaluation['name']))
                else:
                    self.assertEqual(slot['score'], evaluation['score'])
                    self.assertEqual(slot['comment'], evaluation['comment'])
                    self.assertEqual(slot['sources'], evaluation.get('sources', []))

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_browser_scores_and_sorts_the_items(self):
        for slug, expected in (('fruit', FRUIT_RANKING), ('veggie', VEGGIE_RANKING)):
            dom = harness.render(urljoin(self.base, 'topics/%s/' % slug))
            drawn = harness.scored_items(dom)
            self.assertEqual(
                [(i['name'], i['total'], i['filtered']) for i in drawn], expected, slug)

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_browser_shows_what_a_score_is_based_on(self):
        dom = harness.render(urljoin(self.base, 'topics/fruit/'))
        apple = dom.split('>Apple<')[1].split('>Mystery<')[0]
        self.assertIn('href="https://example.com/fruit"', apple)
        self.assertIn('href="https://example.org/orchard"', apple,
                      'every source should be cited, not only the first')
        self.assertIn('>example.com</a>', apple, 'a link should be named for its site')

        lemon = dom.split('>Lemon<')[1]
        self.assertIn('sources: tasted it myself<', lemon,
                      'a source that is not a url should stay text')

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_browser_ranks_requirements_from_their_priority(self):
        dom = harness.render(urljoin(self.base, 'topics/fruit/'))
        self.assertIn('>Sweet<', dom.split('id="requirements"')[1].split('</ul>')[0])
        self.assertIn('>Sour<', dom.split('id="antirequirements"')[1].split('</ul>')[0])
        self.assertIn('>Seasonal<', dom.split('id="nonrequirements"')[1].split('</ul>')[0])


class GeneratorTest(unittest.TestCase):
    """failure paths that should never reach a published site."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def data(self, name, content):
        path = os.path.join(self.tmp.name, 'data')
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, name), 'w') as f:
            f.write(content)
        return path

    def test_it_refuses_to_overwrite_a_foreign_directory(self):
        output = os.path.join(self.tmp.name, 'notours')
        os.makedirs(output)
        keep = os.path.join(output, 'precious.txt')
        with open(keep, 'w') as f:
            f.write('keep me')

        result = harness.build(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing', result.stderr)
        self.assertEqual(harness.read(keep), 'keep me')

    def test_it_replaces_a_site_it_generated_before(self):
        output = os.path.join(self.tmp.name, 'ours')
        self.assertEqual(harness.build(output).returncode, 0)
        stale = os.path.join(output, 'topics', 'gone', 'index.html')
        os.makedirs(os.path.dirname(stale))
        with open(stale, 'w') as f:
            f.write('stale')

        self.assertEqual(harness.build(output).returncode, 0)
        self.assertFalse(os.path.exists(stale))

    def test_a_typo_in_an_evaluation_name_is_rejected(self):
        data = self.data('topics.toml', '''
[t]
requirements = [ { name = "Sweet", priority = 10 } ]
items = [
    { name = "Apple", evaluations = [ { name = "Sweat", score = 1.0, comment = "" } ] },
]
''')
        result = harness.check(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Sweat', result.stderr)

    def test_a_slug_defined_twice_is_rejected(self):
        data = self.data('topics.toml', '[veggie]\nrequirements = []\n')
        os.makedirs(os.path.join(data, 'topics'))
        shutil.copy(os.path.join(harness.TESTDATA, 'topics', 'veggie.toml'),
                    os.path.join(data, 'topics', 'veggie.toml'))

        result = harness.check(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('twice', result.stderr)

    def test_an_empty_data_directory_is_rejected(self):
        result = harness.check(self.data('unrelated.txt', 'nothing here'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no topics found', result.stderr)


MESSY_TOPIC = '''name = "Messy"

# ranked last on purpose
requirements = [
\t{ name = "Unranked" },
\t{ name = "Cheap", priority = 20 },
\t{ name = "Sweet", priority = 10 },
]

items = [
\t{ name = "Zebra", evaluations = [
\t\t{ name = "Cheap", score = 0.25, comment = "keep me" },
\t]},
\t{ name = "Template", skip = true },
\t{ name = "Apple" },
]
'''


class FormatTest(unittest.TestCase):
    """`decide fmt` rewrites the source files, so it gets tested on real ones."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data')
        os.makedirs(os.path.join(self.data, 'topics'))
        self.topic = os.path.join(self.data, 'topics', 'messy.toml')
        self.write(MESSY_TOPIC)

    def write(self, text):
        with open(self.topic, 'w') as f:
            f.write(text)

    def formatted(self):
        return harness.read(self.topic)

    def test_it_fills_in_every_unscored_requirement(self):
        self.assertEqual(harness.fmt(self.data).returncode, 0)
        out = self.formatted()
        # three requirements times three items, minus the one already scored,
        # minus the skipped template
        self.assertEqual(out.count('score = -inf'), 5)
        self.assertEqual(out.count('score = 0.25'), 1)

    def test_it_orders_the_file_the_way_the_site_ranks_it(self):
        harness.fmt(self.data)
        out = self.formatted()
        self.assertLess(out.index('"Sweet"'), out.index('"Cheap"'))
        self.assertLess(out.index('"Cheap"'), out.index('"Unranked"'))
        self.assertLess(out.index('"Template"'), out.index('"Apple"'))
        self.assertLess(out.index('"Apple"'), out.index('"Zebra"'))

    def test_it_keeps_comments_and_indentation(self):
        harness.fmt(self.data)
        out = self.formatted()
        self.assertIn('# ranked last on purpose', out)
        self.assertIn('comment = "keep me"', out)
        self.assertIn('\n\t{ name = "Sweet"', out)
        self.assertIn('\n\t\t{ name = "Sweet"', out)

    def test_it_is_idempotent(self):
        harness.fmt(self.data)
        once = self.formatted()
        result = harness.fmt(self.data)
        self.assertEqual(self.formatted(), once)
        self.assertIn('unchanged', result.stdout)

    def test_check_reports_without_writing(self):
        result = harness.fmt(self.data, '--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not canonical', result.stdout)
        self.assertEqual(self.formatted(), MESSY_TOPIC)

        harness.fmt(self.data)
        self.assertEqual(harness.fmt(self.data, '--check').returncode, 0)

    def test_orphaned_scores_survive_until_pruned(self):
        self.write(MESSY_TOPIC.replace('{ name = "Cheap", priority = 20 },\n', ''))

        result = harness.fmt(self.data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cheap', result.stderr)
        self.assertIn('keep me', self.formatted(), 'scored data must not be lost')

        self.assertEqual(harness.fmt(self.data, '--prune').returncode, 0)
        self.assertNotIn('keep me', self.formatted())

    def test_it_leaves_sources_with_the_score_they_cite(self):
        self.write(
            MESSY_TOPIC.replace(
                '{ name = "Cheap", score = 0.25, comment = "keep me" }',
                '{ name = "Cheap", score = 0.25, comment = "keep me", '
                'sources = ["https://example.com/price", "the shelf label"] }',
            )
        )
        self.assertEqual(harness.fmt(self.data).returncode, 0)
        self.assertIn('sources = ["https://example.com/price", "the shelf label"]',
                      self.formatted())

        # a citation belongs to a score, so an entry filled in as unevaluated
        # has nothing to cite and gains no sources of its own
        self.assertNotIn('-inf, comment = "", sources', self.formatted())
        harness.fmt(self.data)
        self.assertIn('unchanged', harness.fmt(self.data).stdout)

    def test_it_warns_about_scores_that_cite_nothing(self):
        # the messy topic scores exactly one requirement, and cites nothing
        result = harness.fmt(self.data)
        self.assertEqual(result.returncode, 0)
        self.assertIn('1 of 1 scored evaluations have no sources',
                      result.stdout + result.stderr)

        # the entries fmt fills in are unevaluated, so they are not counted
        self.assertNotIn('of 4 scored', result.stdout + result.stderr)

    def test_a_cited_score_draws_no_warning(self):
        self.write(
            MESSY_TOPIC.replace(
                '{ name = "Cheap", score = 0.25, comment = "keep me" }',
                '{ name = "Cheap", score = 0.25, comment = "keep me", '
                'sources = ["https://example.com/price"] }',
            )
        )
        result = harness.fmt(self.data)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('no sources', result.stdout + result.stderr)

    def test_the_warning_survives_a_check_run(self):
        # --check writes nothing, but CI should still hear about it
        result = harness.fmt(self.data, '--check')
        self.assertIn('scored evaluations have no sources',
                      result.stdout + result.stderr)

    def test_a_formatted_topic_still_builds(self):
        harness.fmt(self.data)
        output = os.path.join(self.tmp.name, 'site')
        result = harness.build(output, data=self.data)
        self.assertEqual(result.returncode, 0, result.stderr)
        topic = harness.load_json(os.path.join(output, 'topics', 'messy', 'topic.json'))
        # -inf entries are unknowns, so they must not reach the site as scores
        self.assertEqual([r['name'] for r in topic['requirements']],
                         ['Sweet', 'Cheap', 'Unranked'])
        apple = next(i for i in topic['items'] if i['name'] == 'Apple')
        self.assertEqual(apple['evaluations'], [None, None, None])


if __name__ == '__main__':
    unittest.main()


SPACED_TOPIC = '''name = "Spacing"

requirements = [
\t{ name = "Second", priority = 10 },
\t{ name = "First", priority = 10 },
\t{ name = "Far", priority = 900 },
\t{ name = "Avoid", priority = -40 },
\t{ name = "Shun", priority = -40 },
\t{ name = "Unranked" },
]

items = [
\t{ name = "Apple" },
]
'''


class PrioritySpacingTest(unittest.TestCase):
    """fmt renumbers priorities so there is room to drop something between."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data')
        os.makedirs(os.path.join(self.data, 'topics'))
        self.topic = os.path.join(self.data, 'topics', 'spacing.toml')
        with open(self.topic, 'w') as f:
            f.write(SPACED_TOPIC)

    def test_it_spaces_priorities_five_apart_keeping_file_order_for_ties(self):
        self.assertEqual(harness.fmt(self.data).returncode, 0)
        out = harness.read(self.topic)
        # anti-requirements stay negative so they keep their column, and the
        # two that tied keep the order the file had them in.
        self.assertIn('{ name = "Avoid", priority = -10 }', out)
        self.assertIn('{ name = "Shun", priority = -5 }', out)
        self.assertIn('{ name = "Second", priority = 5 }', out)
        self.assertIn('{ name = "First", priority = 10 }', out)
        self.assertIn('{ name = "Far", priority = 15 }', out)
        self.assertIn('{ name = "Unranked" }', out)

    def test_renumbering_is_idempotent(self):
        harness.fmt(self.data)
        once = harness.read(self.topic)
        result = harness.fmt(self.data)
        self.assertEqual(harness.read(self.topic), once)
        self.assertIn('unchanged', result.stdout)


SOURCES_TOPIC = '''name = "Sources"

requirements = [ { name = "Sweet", priority = 10 } ]

items = [
\t{ name = "Awkward", evaluations = [ { name = "Sweet", score = 1.0, comment = "", sources = ["javascript:alert(1)"] } ] },
\t{ name = "Bare", evaluations = [ { name = "Sweet", score = 1.0, comment = "" } ] },
\t{ name = "Empty", evaluations = [ { name = "Sweet", score = 1.0, comment = "", sources = [] } ] },
\t{ name = "Mixed", evaluations = [ { name = "Sweet", score = 1.0, comment = "", sources = ["https://example.com/review", "a friend told me"] } ] },
\t{ name = "Prose", evaluations = [ { name = "Sweet", score = 1.0, comment = "", sources = ["tasted it myself"] } ] },
]
'''


class SourcesTest(unittest.TestCase):
    """sources cite where a score came from. they should read as citations,
    and only ever be followable when a source is a url a browser may follow."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        data = os.path.join(cls.tmp.name, 'data')
        os.makedirs(os.path.join(data, 'topics'))
        with open(os.path.join(data, 'topics', 'sources.toml'), 'w') as f:
            f.write(SOURCES_TOPIC)

        cls.output = os.path.join(cls.tmp.name, SITE_DIR)
        result = harness.build(cls.output, data=data)
        if result.returncode != 0:
            raise AssertionError('build failed:\n%s%s' % (result.stdout, result.stderr))
        cls.server = harness.WebServer(cls.tmp.name).__enter__()
        cls.page = urljoin(cls.server.url, '%s/topics/sources/' % SITE_DIR)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        cls.tmp.cleanup()

    def cards(self):
        return harness.item_cards(harness.render(self.page))

    def test_sources_reach_the_published_data(self):
        topic = harness.load_json(os.path.join(self.output, 'topics', 'sources', 'topic.json'))
        cited = {i['name']: i['evaluations'][0]['sources'] for i in topic['items']}
        self.assertEqual(cited['Mixed'], ['https://example.com/review', 'a friend told me'])
        self.assertEqual(cited['Prose'], ['tasted it myself'])
        self.assertEqual(cited['Awkward'], ['javascript:alert(1)'])
        self.assertEqual(cited['Bare'], [], 'an uncited score still carries the field')
        self.assertEqual(cited['Empty'], [])

    def test_a_source_that_is_not_a_string_is_rejected(self):
        data = os.path.join(self.tmp.name, 'broken')
        os.makedirs(os.path.join(data, 'topics'), exist_ok=True)
        with open(os.path.join(data, 'topics', 'sources.toml'), 'w') as f:
            f.write(SOURCES_TOPIC.replace('["tasted it myself"]', '[7]'))

        result = harness.check(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sources', result.stderr)

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_only_a_url_source_becomes_a_link(self):
        cards = self.cards()
        self.assertIn('href="https://example.com/review"', cards['Mixed'])
        self.assertIn('>example.com</a>', cards['Mixed'], 'a link should be named for its site')
        self.assertIn('a friend told me<', cards['Mixed'], 'every source is cited, url or not')
        self.assertIn('sources: tasted it myself<', cards['Prose'])
        self.assertIn('sources: javascript:alert(1)<', cards['Awkward'], 'a citation is text')
        for href in re.findall(r'\bhref="([^"]*)"', ''.join(cards.values())):
            self.assertFalse(href.lower().startswith('javascript:'),
                             '%s would run script when followed' % href)

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_an_uncited_score_says_nothing_about_sources(self):
        cards = self.cards()
        for name in ('Bare', 'Empty'):
            self.assertNotIn('sources:', cards[name], name)


# drives a real drag and reports where the cards sat before it started and
# where they sat while the requirement was still in flight.
DRAG_PROBE = r"""
(function () {
  var out = document.createElement('pre');
  out.id = 'probe';
  out.textContent = '{}';
  document.body.appendChild(out);

  function report(o) { out.textContent = JSON.stringify(o); }

  // document coordinates, so scrolling the page does not read as the layout
  // moving underneath the drag.
  function boxes() {
    return Array.prototype.map.call(document.querySelectorAll('.card'), function (card) {
      var box = card.getBoundingClientRect();
      return [Math.round(box.left + window.scrollX), Math.round(box.top + window.scrollY)];
    });
  }

  function middle(el) {
    var box = el.getBoundingClientRect();
    return {x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2)};
  }

  // sortable listens for pointer events, so mouse events alone drive nothing.
  function fire(el, type, at) {
    el.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, composed: true, view: window,
      pointerId: 1, pointerType: 'mouse', isPrimary: true,
      clientX: at.x, clientY: at.y, screenX: at.x, screenY: at.y,
      button: 0, buttons: 1
    }));
  }

  var tries = 0;
  function run() {
    var handle = document.querySelector('#requirements .list-item .handle');
    var target = document.getElementById('antirequirements');
    if (!handle || !target) {
      if (++tries > 100) return report({error: 'page never rendered'});
      return setTimeout(run, 50);
    }

    // sortable decides where the pointer is with elementFromPoint, which only
    // sees what is on screen. a short window puts the target below the fold,
    // so bring it into view first. the handle needs no such help: pointerdown
    // goes straight to it rather than through hit testing.
    target.scrollIntoView({block: 'center'});

    var before = boxes();
    var started = target.querySelectorAll('.list-item').length;
    var grab = middle(handle);

    function aim() {
      return middle(target.querySelector('.list-item') || target);
    }

    fire(handle, 'pointerdown', grab);
    fire(document, 'pointermove', {x: grab.x, y: grab.y + 12});

    // where the cards sit once the drag is under way and the lists have made
    // room. everything after this point must not move them again.
    var settled = null;
    var attempts = 0;

    function walk() {
      var landed = target.querySelectorAll('.list-item').length > started;
      if (landed || attempts >= 40) return finish(landed);
      attempts++;
      // re-aim every tick rather than following a path worked out in advance:
      // making room moves the target, and so does the row once it lands.
      var at = aim();
      fire(document, 'pointermove', at);
      fire(target, 'pointermove', at);
      setTimeout(walk, 20);
    }

    function finish(landed) {
      var during = boxes();
      var flying = document.querySelectorAll(
        '.sortable-ghost, .sortable-drag, .sortable-fallback').length > 0;
      fire(document, 'pointerup', aim());
      report({viewport: [window.innerWidth, window.innerHeight],
              flying: flying, moved: landed, attempts: attempts,
              before: before, settled: settled, during: during});
    }

    setTimeout(function () {
      settled = boxes();
      setTimeout(walk, 20);
    }, 30);
  }
  run();
})();
"""


class DragTest(unittest.TestCase):
    """the layout must hold still while a requirement is in flight."""

    # wide enough that the cards actually pack into several columns, which is
    # where a mid-drag reflow is most obvious.
    WINDOW = (1600, 1000)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = os.path.join(self.tmp.name, SITE_DIR)
        result = harness.build(self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        harness.probe(os.path.join(self.output, 'topics', 'fruit', 'index.html'),
                      DRAG_PROBE)
        self.server = harness.WebServer(self.tmp.name).__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.base = urljoin(self.server.url, SITE_DIR + '/')

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_cards_hold_still_while_a_requirement_is_dragged(self):
        dom = harness.render(urljoin(self.base, 'topics/fruit/'), window=self.WINDOW)
        found = harness.probe_result(dom)
        self.assertNotIn('error', found, found)
        self.assertTrue(found['flying'], 'the drag never started, so nothing was tested')
        self.assertTrue(found['moved'],
                        'the requirement never reached the other list at %s after '
                        '%s tries, so no card changed height and the test proved '
                        'nothing' % (found['viewport'], found['attempts']))
        self.assertNotEqual(
            found['settled'], found['before'],
            'the lists never made room, so there was nothing to drop into')
        self.assertEqual(
            found['during'], found['settled'],
            'cards moved while a requirement was in flight at %s: %s -> %s'
            % (found['viewport'], found['settled'], found['during']))
