"""Comments out of the stylesheets and the raw index.html template, before
they are served (server.py: _send_file for every .css, _index_template for
the template). styles.css is about 45% comments and index.html about 30%:
notes for whoever edits them, bytes for every first visit.

Both are small tokenizers, not regexes, so nothing that only looks like a
comment is touched:

  css(text)       drops /* ... */ outside strings ("..." and '...', escapes
                  included) and outside an unquoted url(...); keeps /*! ... */.
  html(text)      drops <!-- ... --> in markup only: never inside <script>,
                  <style>, <textarea> or <title> (raw text, where "<!--" is
                  not a comment) or inside a tag (an attribute may hold
                  "<!--"). Keeps the markers that mean something to someone
                  else: <!--email_off--> / <!--/email_off--> (Cloudflare's
                  Email Address Obfuscation), <!--tN--> (server.py
                  _text_out's word marks, restored by app.js) and
                  conditional comments (<!--[if ...]>).

A comment that is the only thing on its line takes the line with it. Any
other goes without a trace in HTML; in CSS it leaves one space unless a space
or a delimiter already separates its neighbours (a/**/b is two tokens, ab one).

Only the raw template is ever stripped, never a rendered page: the guides'
<!--tN--> marks and /privacy's email_off markers are put in after this runs.
"""

import re

_CSS_DELIM = set(" \t\r\n\f{};:,>+~()[]=")
_HTML_KEEP = re.compile(r"<!--(?:t\d+|/?email_off|\[if\b[^\]]*\]>)")
_RAW_TEXT = ("script", "style", "textarea", "title")
_RAW_OPEN = re.compile(r"<(%s)\b" % "|".join(_RAW_TEXT), re.I)


def _at_line_start(out):
    """True when everything written since the last newline (or since the
    start) is whitespace in "text" tokens; trims that whitespace off when so."""
    k = len(out) - 1
    while k >= 0:
        kind, t = out[k]
        if kind != "text":
            return False
        nl = t.rfind("\n")
        if nl >= 0:
            if t[nl + 1:].strip():
                return False
            out[k][1] = t[:nl + 1]
            break
        if t.strip():
            return False
        k -= 1
    for x in out[k + 1:]:
        x[1] = ""
    return True


def _join(tokens, delim=None):
    """Glue (kind, text) tokens back together, dropping the "drop" ones the
    way the module doc says. kind: "text" (may be trimmed), "lit" (strings,
    tags, raw text: never trimmed) or "drop". delim: the characters that
    already separate two tokens, so a comment between two others becomes one
    space (CSS); None never puts a space in (HTML: a comment adds no
    whitespace to the text around it, so "a<!-- -->b" renders "ab")."""
    tokens = [list(x) for x in tokens]
    out = []
    i, n = 0, len(tokens)
    while i < n:
        if tokens[i][0] != "drop":
            out.append(tokens[i])
            i += 1
            continue
        j = i
        while j < n and tokens[j][0] == "drop":   # comments back to back count as one
            j += 1
        nxt = tokens[j] if j < n else None
        ends_line = nxt is None or (nxt[0] == "text" and "\n" in nxt[1]
                                    and not nxt[1].split("\n", 1)[0].strip())
        if ends_line and _at_line_start(out):
            if nxt is not None:
                nxt[1] = nxt[1].split("\n", 1)[1]
        elif delim is not None:
            before = "".join(t for _, t in out[-2:])
            after = nxt[1] if nxt else ""
            a = before[-1:] or " "
            b = after[:1] or " "
            if a not in delim and b not in delim:
                out.append(["text", " "])
        i = j
    return "".join(t for _, t in out)


def css_tokens(src):
    """[(kind, text)] for a stylesheet: comments "drop" (/*! ones "lit"),
    strings and unquoted url() bodies "lit", everything else "text"."""
    toks, buf = [], []
    i, n = 0, len(src)

    def flush():
        if buf:
            toks.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        c = src[i]
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            flush()
            toks.append(("lit", src[i:j]))
            i = j
        elif c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            flush()
            toks.append(("lit" if src.startswith("/*!", i) else "drop", src[i:j]))
            i = j
        elif c in "uU" and src[i:i + 4].lower() == "url(" and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] in "-_")):
            k = i + 4
            while k < n and src[k] in " \t\r\n\f":
                k += 1
            if k < n and src[k] in "\"'":
                buf.append(src[i:k])          # a quoted url(): the string branch takes it
                i = k
            else:
                j = src.find(")", k)
                j = n if j < 0 else j + 1
                flush()
                toks.append(("lit", src[i:j]))
                i = j
        else:
            buf.append(c)
            i += 1
    flush()
    return toks


def css(src):
    """src with its comments taken out (see the module doc)."""
    return _join(css_tokens(src), _CSS_DELIM)


def html_tokens(src):
    """[(kind, text)] for an HTML template: droppable comments "drop", kept
    markers, tags and raw-text elements "lit", text between them "text"."""
    toks, i, n = [], 0, len(src)
    text_start = 0

    def flush(upto):
        if upto > text_start:
            toks.append(("text", src[text_start:upto]))

    while i < n:
        lt = src.find("<", i)
        if lt < 0:
            break
        if src.startswith("<!--", lt):
            end = src.find("-->", lt + 4)
            end = n if end < 0 else end + 3
            flush(lt)
            toks.append(("lit" if _HTML_KEEP.match(src, lt) else "drop", src[lt:end]))
            i = text_start = end
            continue
        m = _RAW_OPEN.match(src, lt)
        if m:
            close = re.compile(r"</%s\s*>" % m.group(1), re.I).search(src, lt)
            end = n if close is None else close.end()
            flush(lt)
            toks.append(("lit", src[lt:end]))
            i = text_start = end
            continue
        if lt + 1 < n and (src[lt + 1].isalpha() or src[lt + 1] in "/!?"):
            # A tag: to its closing ">", quoted attribute values skipped whole.
            j, q = lt + 1, None
            while j < n:
                ch = src[j]
                if q:
                    if ch == q:
                        q = None
                elif ch in "\"'":
                    q = ch
                elif ch == ">":
                    break
                j += 1
            end = min(j + 1, n)
            flush(lt)
            toks.append(("lit", src[lt:end]))
            i = text_start = end
            continue
        i = lt + 1
    flush(n)
    return toks


def html(src):
    """src with its droppable comments taken out (see the module doc)."""
    return _join(html_tokens(src))
