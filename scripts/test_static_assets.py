#!/usr/bin/env python3
"""Static files as served: comments out of the stylesheets and the index.html
template (fxtracker/strip_comments.py), the in-memory copies _send_file keeps
(raw and gzipped), and the font files cached as immutable. In-process: no
network, a loopback server for the routes.

    /usr/bin/python3 scripts/test_static_assets.py

What it holds the code to:
  * the tokenizers: comments go, strings, url(...) bodies, /*! */, script and
    style contents, attribute values and the markers others rely on
    (<!--tN-->, <!--email_off-->, conditional comments) stay; a comment alone
    on its line takes the line; in HTML a comment never adds a space;
  * on the real files: styles.css and fonts/jakarta.css keep every CSS token
    in order (strings, url bodies, punctuation, words: only comments and
    whitespace differ) and no comment is left; index.html parses to the same
    tags, attributes and text (whitespace runs compared collapsed) with every
    comment gone; styles.css drops to under half its gzipped size;
  * the routes: /styles.css?v= is the stripped file, gzipped to the bytes
    kept in memory, the same on the next request; HEAD has no body; with
    FX_STRIP_COMMENTS off (STRIP_COMMENTS False) it is the file as written;
    the homepage has no <!-- -->, a guide keeps its <!--tN--> word marks and
    restores them all (every N in #shellText), /privacy keeps email_off;
  * _static_bytes: a text file is read once and gzipped once while its
    mtime and size hold, read again when either changes; an image is never
    kept; the font files go out immutable, jakarta.css and og.png not.
"""
import gzip
import html.parser
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import strip_comments as sc  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
PUBLIC = os.path.join(ROOT, "public")
read = lambda rel: open(os.path.join(PUBLIC, rel), encoding="utf-8").read()

# --- the tokenizers --------------------------------------------------------------------
CSS_CASES = [
    ("a\n  /* c */\nb", "a\nb"),
    ("a\n/*1*/\n/*2*/\nb", "a\nb"),
    ("a/**/b", "a b"),
    ("x{color:red;/* y */}", "x{color:red;}"),
    ('a{content:"/* not */"}', 'a{content:"/* not */"}'),
    ("a{content:'it\\'s /* not */'}", "a{content:'it\\'s /* not */'}"),
    ("a{background:url(/x/*y*/z.png)}", "a{background:url(/x/*y*/z.png)}"),
    ('a{background:url( "q/*.png")}/*c*/', 'a{background:url( "q/*.png")}'),
    ("/*! keep */\n.a{}", "/*! keep */\n.a{}"),
    ("/* lead */\n.a{}\n/* tail */", ".a{}\n"),
    ("a{x:1}\n  /* multi\n  line */\nb{}", "a{x:1}\nb{}"),
]
bad = [(s, sc.css(s), w) for s, w in CSS_CASES if sc.css(s) != w]
results.append(ok(not bad, "css(): %d cases (strings, url(), /*!, own-line, a/**/b) %s" % (len(CSS_CASES), bad or "")))
HTML_CASES = [
    ("<p>a</p>\n  <!-- c -->\n<p>b</p>", "<p>a</p>\n<p>b</p>"),
    ("<p>a<!-- c -->b</p>", "<p>ab</p>"),
    ("<script>var s='<!-- x -->';</script>", "<script>var s='<!-- x -->';</script>"),
    ("<style>/*<!-- s -->*/</style>", "<style>/*<!-- s -->*/</style>"),
    ('<a title="<!-- t -->">x</a>', '<a title="<!-- t -->">x</a>'),
    ("<!--email_off--><a>m</a><!--/email_off-->", "<!--email_off--><a>m</a><!--/email_off-->"),
    ("<div><!--t12--></div>", "<div><!--t12--></div>"),
    ("<!--[if IE]><p>x</p><![endif]-->", "<!--[if IE]><p>x</p><![endif]-->"),
    ("<textarea><!-- lit --></textarea>", "<textarea><!-- lit --></textarea>"),
    ("x {{TOK}} <!-- {{NOPE}} --> y", "x {{TOK}}  y"),
]
bad = [(s, sc.html(s), w) for s, w in HTML_CASES if sc.html(s) != w]
results.append(ok(not bad, "html(): %d cases (raw text, attributes, kept markers, no added space) %s"
                  % (len(HTML_CASES), bad or "")))

# --- the real files ----------------------------------------------------------------------
CSS_TOK = re.compile(r"[{};:,>+~()\[\]=]|[^\s{};:,>+~()\[\]=]+")


def css_sig(src):
    """The significant tokens: comments dropped, strings and url bodies whole,
    the rest split at whitespace and CSS punctuation."""
    out = []
    for kind, t in sc.css_tokens(src):
        if kind == "drop":
            continue
        out += [t] if kind == "lit" else CSS_TOK.findall(t)
    return out


for rel in ("styles.css", "fonts/jakarta.css"):
    src = read(rel)
    out = sc.css(src)
    left = [t for k, t in sc.css_tokens(out) if k == "drop"]
    results.append(ok(css_sig(src) == css_sig(out) and not left and "/*" not in re.sub(r"\"[^\"]*\"|'[^']*'", "", out),
                      "%s: every token kept in order, no comment left (%d -> %d bytes)" % (rel, len(src), len(out))))
css_src = read("styles.css")
gz_before, gz_after = len(gzip.compress(css_src.encode(), 6)), len(gzip.compress(sc.css(css_src).encode(), 6))
results.append(ok(gz_after * 2 < gz_before, "styles.css gzipped: %d -> %d bytes" % (gz_before, gz_after)))


class Events(html.parser.HTMLParser):
    """Tags, attributes and text, comments counted apart; text runs merged
    and their whitespace collapsed (a comment removed between two runs
    leaves them one run)."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.ev, self.comments, self.text = [], 0, []

    def _flush(self):
        if self.text:
            t = re.sub(r"\s+", " ", "".join(self.text))
            if t.strip() or (self.ev and self.ev[-1][0] != "text"):
                self.ev.append(("text", t))
            self.text = []

    def handle_starttag(self, tag, attrs):
        self._flush()
        self.ev.append(("start", tag, tuple(attrs)))

    def handle_endtag(self, tag):
        self._flush()
        self.ev.append(("end", tag))

    def handle_data(self, d):
        self.text.append(d)

    def handle_entityref(self, n):
        self.text.append("&%s;" % n)

    def handle_charref(self, n):
        self.text.append("&#%s;" % n)

    def handle_comment(self, d):
        self.comments += 1

    def close(self):
        super().close()
        self._flush()


def events(doc):
    p = Events()
    p.feed(doc)
    p.close()
    return p


tpl = read("index.html")
e1, e2 = events(tpl), events(sc.html(tpl))
results.append(ok(e1.ev == e2.ev and e1.comments > 50 and e2.comments == 0,
                  "index.html: the same tags, attributes and text, %d comments -> %d (%d -> %d bytes)"
                  % (e1.comments, e2.comments, len(tpl), len(sc.html(tpl)))))

# --- the routes --------------------------------------------------------------------------
server.Handler.log_message = lambda self, *a: None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def get(path, method="GET", gz=False):
    req = urllib.request.Request(BASE + path, method=method, headers={"Accept-Encoding": "gzip"} if gz else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


try:
    stripped = sc.css(css_src).encode("utf-8")
    st, hd, body = get("/styles.css?v=1")
    results.append(ok(st == 200 and body == stripped and hd.get("Cache-Control") == "public, max-age=31536000, immutable",
                      "/styles.css?v= is the stripped stylesheet, immutable (%d bytes)" % len(body)))
    st, hd, body = get("/styles.css?v=1", gz=True)
    path = os.path.join(PUBLIC, "styles.css")
    kept = server._static_memo.get(path)
    results.append(ok(hd.get("Content-Encoding") == "gzip" and gzip.decompress(body) == stripped
                      and kept is not None and kept[2] == body and int(hd.get("Content-Length")) == len(body),
                      "gzipped, the memo's copy sent as is (%d bytes)" % len(body)))
    st2, _, body2 = get("/styles.css?v=1", gz=True)
    results.append(ok(body2 == body and server._static_memo.get(path) is kept, "the next request is the same bytes, from the memo"))
    st, hd, body = get("/styles.css?v=1", method="HEAD", gz=True)
    results.append(ok(st == 200 and body == b"", "HEAD /styles.css: 200, no body"))

    server.STRIP_COMMENTS = False
    server._static_memo.clear()
    _, _, raw = get("/styles.css?v=1")
    server.STRIP_COMMENTS = True
    server._static_memo.clear()
    results.append(ok(raw == css_src.encode("utf-8"), "with FX_STRIP_COMMENTS=0 the stylesheet goes out as written"))

    _, hd, _ = get("/fonts/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yygg_vb.woff2")
    _, hd2, jk = get("/fonts/jakarta.css")
    _, hd3, png = get("/og.png")
    results.append(ok(hd.get("Cache-Control") == "public, max-age=31536000, immutable"
                      and hd2.get("Cache-Control") == "public, max-age=300" and b"/*" not in jk
                      and hd3.get("Cache-Control") == "public, max-age=300",
                      "fonts: the .woff2 files immutable, jakarta.css 5 minutes (stripped), og.png as before"))
    results.append(ok(os.path.join(PUBLIC, "og.png") not in server._static_memo
                      and os.path.join(PUBLIC, "fonts/jakarta.css") in server._static_memo,
                      "images are read per request, never kept; text is kept"))

    _, _, home = get("/")
    home = home.decode("utf-8")
    results.append(ok("<!--" not in home, "the homepage has no <!-- --> left (%d bytes)" % len(home)))
    _, _, guide = get("/guide/japan")
    guide = guide.decode("utf-8")
    marks = set(int(n) for n in re.findall(r"<!--t(\d+)-->", guide))
    m = re.search(r'<script type="application/json" id="shellText">(.*?)</script>', guide, re.S)
    words = json.loads(m.group(1)) if m else []
    other = [c for c in re.findall(r"<!--.*?-->", guide, re.S) if not re.fullmatch(r"<!--t\d+-->", c)]
    results.append(ok(marks and marks == set(range(len(words))) and not other,
                      "a guide keeps its %d word marks, each with its words in #shellText, and no other comment" % len(marks)))
    _, _, priv = get("/privacy")
    results.append(ok(priv.decode("utf-8").count("<!--email_off-->") >= 3, "/privacy keeps its email_off markers"))
finally:
    httpd.shutdown()

# --- _static_bytes on a file of its own ---------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.css")
    with open(p, "w") as f:
        f.write("/* note */\n.a { color: red; }\n" + ".b{}\n" * 400)
    reads = []
    real_open = open

    def counting_open(f, *a, **k):
        if f == p:
            reads.append(1)
        return real_open(f, *a, **k)

    server.open = counting_open      # the module's global open, shadowed for the test
    try:
        always = lambda raw: True
        r1, g1 = server._static_bytes(p, always)
        r2, g2 = server._static_bytes(p, always)
        n_same = len(reads)
        time.sleep(0.01)
        with real_open(p, "w") as f:
            f.write(".c { color: blue; }\n" * 300)
        os.utime(p, None)
        r3, g3 = server._static_bytes(p, always)
        r4, g4 = server._static_bytes(p, lambda raw: False)
    finally:
        del server.open
    results.append(ok(r1 == r2 and g1 is g2 and n_same == 1 and r1.startswith(b".a { color: red; }")
                      and gzip.decompress(g1) == r1,
                      "read and gzipped once while mtime and size hold (reads: %d), the comment out" % n_same))
    results.append(ok(len(reads) == 2 and r3.startswith(b".c") and gzip.decompress(g3) == r3 and g4 is None and r4 == r3,
                      "read again once the file changes; no gzipped copy handed out when it isn't wanted"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
