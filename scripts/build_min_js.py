#!/usr/bin/env python3
"""Builds public/app.min.js, the copy of public/app.js that /app.js serves
(review #34: 301 KB of app.js gzipped -> about 143 KB minified).

    /usr/bin/python3 scripts/build_min_js.py           # after every app.js edit
    /usr/bin/python3 scripts/build_min_js.py --check   # exit 1 while it is stale

Writes public/app.min.js and public/app.min.js.sha256, the sha256 of the
app.js it was built from (shasum's format: `cd public && shasum -a 256 -c
app.min.js.sha256` checks it). Commit the three files together.
server.py (_app_js_file) serves the minified copy for /app.js only while
that hash is app.js's own. An app.js edited without a rebuild goes out as
written, with one [min-js] line in the log, so a forgotten rebuild ships the
bigger file, never stale code; scripts/test_min_js.py fails until it is
rebuilt. FX_MIN_JS=0 (Render -> Environment) serves app.js as written.

esbuild is pinned (ESBUILD below) and run through npx, which fetches it from
npm on first use. Node only on the machine that builds: the server stays
stdlib Python. The flags:
  --minify          whitespace, syntax and local names. Top-level names stay
                    as written: with no --format, esbuild reads a plain
                    script, whose top-level names are globals (the inline
                    scripts in index.html, the jsc tests and the CDP checks
                    use them by name). scripts/test_min_js.py holds it to that.
  --target=es2020   app.js already needs ES2020 (??). A later target would let
                    esbuild write syntax app.js never uses (||=, class fields).
  --charset=utf8    ⓘ, — and the emoji as written, not as \\u escapes.
  --legal-comments=none
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
SRC = os.path.join(PUBLIC, "app.js")
OUT = os.path.join(PUBLIC, "app.min.js")
SHA = OUT + ".sha256"
ESBUILD = "esbuild@0.25.12"
FLAGS = ["--minify", "--target=es2020", "--charset=utf8", "--legal-comments=none", "--loader=js"]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stored_hash():
    """The app.js sha256 app.min.js.sha256 names, or None."""
    try:
        with open(SHA, encoding="utf-8") as f:
            word = (f.read().split() or [""])[0].lower()
    except OSError:
        return None
    return word if len(word) == 64 and all(c in "0123456789abcdef" for c in word) else None


def minify(src):
    """app.js minified by the pinned esbuild, as bytes. Exits on any warning."""
    run = subprocess.run(["npx", "--yes", ESBUILD] + FLAGS, input=src, capture_output=True, timeout=55)
    if run.returncode != 0 or run.stderr.strip():
        sys.exit("esbuild failed (exit %d):\n%s" % (run.returncode, run.stderr.decode("utf-8", "replace")[-3000:]))
    return run.stdout


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def main():
    with open(SRC, "rb") as f:
        src = f.read()
    digest = sha256(src)
    if "--check" in sys.argv[1:]:
        current = stored_hash() == digest and os.path.isfile(OUT)
        print("app.min.js is %s" % ("current" if current else
                                    "STALE: run /usr/bin/python3 scripts/build_min_js.py"))
        sys.exit(0 if current else 1)
    out = minify(src)
    # The output must parse as a script before anything is replaced.
    check = subprocess.run(["node", "--check", "-"], input=out, capture_output=True, timeout=55)
    if check.returncode != 0:
        sys.exit("node --check refused esbuild's output:\n%s" % check.stderr.decode("utf-8", "replace")[-3000:])
    # The minified file first, then the hash that vouches for it: stopped in
    # between, the old hash names the old app.js and the server falls back.
    write_atomic(OUT, out)
    write_atomic(SHA, ("%s  app.js\n" % digest).encode("ascii"))
    print("public/app.min.js: %d -> %d bytes (%s, app.js sha256 %s)" % (len(src), len(out), ESBUILD, digest[:12]))


if __name__ == "__main__":
    main()
