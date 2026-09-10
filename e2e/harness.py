#!/usr/bin/env python3
""" shared plumbing for driving a generated site from the outside. """

import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECIDE = os.path.join(ROOT, 'target', 'release', 'decide')
TESTDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'testdata')

CHROME = shutil.which('google-chrome') or shutil.which('chromium')

# long enough for the page script to run to completion under virtual time.
RENDER_BUDGET_MS = 4000


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class WebServer:
    """serves a directory on a random localhost port for the life of a test."""

    def __init__(self, root):
        handler = functools.partial(QuietHandler, directory=root)
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return 'http://%s:%d/' % (host, port)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


class RefParser(HTMLParser):
    """collects the urls a page depends on."""

    def __init__(self):
        super().__init__()
        self.refs = []
        self.title = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ('href', 'src'):
            if attrs.get(name):
                self.refs.append(attrs[name])
        if tag == 'title':
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = data.strip()


def build(output, data=TESTDATA):
    """run the generator the way `make site` does, against fixture data."""
    return subprocess.run(
        [DECIDE, 'build', '--data', data, '--output', output,
         '--templates', os.path.join(ROOT, 'templates'),
         '--assets', os.path.join(ROOT, 'web', 'dist')],
        cwd=ROOT, capture_output=True, text=True)


def check(data):
    return subprocess.run([DECIDE, 'check', '--data', data],
                          cwd=ROOT, capture_output=True, text=True)


def fmt(data, *flags):
    return subprocess.run([DECIDE, 'fmt', '--data', data, *flags],
                          cwd=ROOT, capture_output=True, text=True)


def render(url, window=None):
    """load a url in a real browser and return the dom its script produced."""
    size = ['--window-size=%d,%d' % window] if window else []
    with tempfile.TemporaryDirectory() as profile:
        result = subprocess.run(
            [CHROME, '--headless', '--disable-gpu', '--no-sandbox',
             '--user-data-dir=' + profile, *size,
             '--virtual-time-budget=%d' % RENDER_BUDGET_MS, '--dump-dom', url],
            capture_output=True, text=True, timeout=120)
    return result.stdout


def probe(path, script):
    """add a script to a built page so a headless render can drive the ui and
    leave its findings in #probe for the dump to carry back out."""
    html = read(path)
    assert '</body>' in html, path
    with open(path, 'w') as f:
        f.write(html.replace('</body>', '<script>%s</script></body>' % script))


def probe_result(dom):
    match = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
    assert match, 'probe left no result'
    text = match.group(1)
    for entity, char in (('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&amp;', '&')):
        text = text.replace(entity, char)
    return json.loads(text)


def scored_items(dom):
    """the item names and totals the browser drew, in the order drawn."""
    listing = re.search(r'<ul class="list" id="items">(.*?)</ul>', dom, re.S)
    if not listing:
        return []
    pattern = r'<li class="(list-item item[^"]*)">([^<]*)<span class="badge">([^<]*)</span>'
    return [
        {'name': name.strip(), 'total': int(total), 'filtered': 'filtered' in classes}
        for classes, name, total in re.findall(pattern, listing.group(1))
    ]


def read(path):
    with open(path) as f:
        return f.read()


def data_file(html):
    """the data file a topic page says it loads."""
    match = re.search(r'<meta name="topic-data" content="([^"]*)"', html)
    assert match, 'page does not name a topic data file'
    return match.group(1)


def load_json(path):
    with open(path) as f:
        return json.load(f)
