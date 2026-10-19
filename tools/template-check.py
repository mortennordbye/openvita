#!/usr/bin/env python3
"""Check a template: render the fictional example profile in it and look for anything lost.

    python3 tools/template-check.py NAME [C] [--lang en|nb]

The sample CV is a draft of openself/example with every block of the shared markup in it: a photo
(a grey placeholder), a highlight and one h2.page-title.same-page. The check fails when the layout
names unknown slots, or when a heading, the name or an entry title is missing from the PDF text
(hidden by the CSS, or placed off the page). It writes build/templates/<name>/check.pdf and a PNG
of every page, for checking the rest by eye: no entry alone on a page, no heading at the bottom of
one, the name on one line.
"""

import argparse
import glob
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft  # noqa: E402
import profiles  # noqa: E402
import render  # noqa: E402
import templates  # noqa: E402

EXAMPLE = os.path.join(profiles.ROOT, "openself", "example")
PHOTO = ('<div class="photo"><img alt="" src="data:image/svg+xml,'
         "%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E"
         "%3Crect width='300' height='300' fill='%23b8b8be'/%3E%3C/svg%3E\"></div>")
WORDS = {"en": "Highlight", "nb": "Utvalgt"}


def sample(t, lang):
    """The example profile drafted in template t, with the blocks a draft leaves out added."""
    text = draft.build("example", t, lang, profile_dir=EXAMPLE)
    text = text.replace("<!-- /brand -->", "<!-- /brand -->\n" + PHOTO, 1)
    first = re.search(r'<section class="timeline projects">\s*(<div class="entry".*?\n  </div>)', text, re.S)
    if first:
        highlight = f'<section class="highlight">\n  <h2 class="section">{WORDS[lang]}</h2>\n{first.group(1)}\n</section>\n\n'
        text = text.replace('<h2 class="page-title">', highlight + '<h2 class="page-title">', 1)
    titles = [m.start() for m in re.finditer(r'<h2 class="page-title">', text)]
    if len(titles) > 1:
        at = titles[1]
        text = text[:at] + '<h2 class="page-title same-page">' + text[at + len('<h2 class="page-title">'):]
    return text


def expected(text):
    """Text that must show in the PDF: the name, every heading and every entry title."""
    found = re.findall(r'<h1 class="name">(.*?)</h1>|<h2[^>]*>(.*?)</h2>|<h3>(.*?)</h3>', text, re.S)
    return [html.unescape(re.sub(r"<[^>]+>", "", next(g for g in m if g))).strip() for m in found]


def squash(s):
    # Letter-spaced headings come out of the PDF as "C E R T I F I C AT I O N S".
    return re.sub(r"\s+", "", s).lower()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("c", nargs="?", default="")
    ap.add_argument("--lang", default="en", choices=sorted(WORDS))
    a = ap.parse_args(argv)
    t = templates.find(a.name, a.c)
    if not t:
        raise SystemExit(f"unknown template {a.name!r} (see make templates" + (f" C={a.c})" if a.c else ")"))
    errors, warnings = [], []
    if t["markup"] != templates.MARKUP:
        errors.append(f"styles its own markup ({t['markup']}): only CVs in that markup can use it, and no draft can be "
                      "written for it. Style the shared markup instead (TEMPLATES.md), with a layout.html if the blocks "
                      "need another order or wrappers")
    if t["layout"]:
        with open(t["layout"], encoding="utf-8") as fh:
            e, w = templates.layout_problems(fh.read())
        errors += e
        warnings += w
    for line in warnings:
        print(f"warning: {line}")
    if errors:
        for line in errors:
            print(f"error: {line}")
        return 1
    out = os.path.join(profiles.ROOT, "build", "templates", t["name"])
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "page-*.png")):
        os.remove(old)
    text = sample(t, a.lang)
    with open(os.path.join(out, "check.html"), "w", encoding="utf-8") as fh:
        fh.write(templates.laid_out(a.c, text))
    pdf = os.path.join(out, "check.pdf")
    ok, err = render.pdf_text(a.c, text, out, pdf)
    if not ok:
        print(f"error: rendering failed\n{err}")
        return 1
    ok, pdf_text = render.pdf_to_text(pdf)
    if not ok:
        print(f"error: could not read the PDF text\n{pdf_text}")
        return 1
    seen = squash(pdf_text)
    missing = [s for s in expected(text) if squash(s) not in seen]
    render.png(pdf, os.path.join(out, "page"), dpi=72)
    pages = sorted(glob.glob(os.path.join(out, "page-*.png")))
    for s in missing:
        print(f"error: not in the PDF: {s!r}")
    print(f"{len(pages)} page(s): {os.path.relpath(pdf, profiles.ROOT)}")
    for p in pages:
        print(f"  {os.path.relpath(p, profiles.ROOT)}")
    if missing:
        return 1
    print(f"{t['label']}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
