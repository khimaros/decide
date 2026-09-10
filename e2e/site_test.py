#!/usr/bin/env python3
""" end to end tests for the generated site. """

import json
import os
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

    def test_index_links_to_every_topic(self):
        refs = self.parsed(self.base).refs
        for slug in ('fruit', 'veggie'):
            self.assertIn('topics/%s/index.html' % slug, refs)

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

    @unittest.skipUnless(harness.CHROME, 'no chrome available')
    def test_browser_scores_and_sorts_the_items(self):
        for slug, expected in (('fruit', FRUIT_RANKING), ('veggie', VEGGIE_RANKING)):
            dom = harness.render(urljoin(self.base, 'topics/%s/' % slug))
            drawn = harness.scored_items(dom)
            self.assertEqual(
                [(i['name'], i['total'], i['filtered']) for i in drawn], expected, slug)

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
