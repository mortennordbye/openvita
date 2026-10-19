#!/usr/bin/env python3
"""CV templates: where they are found, and how a CV refers to them (see TEMPLATES.md).

    python3 tools/templates.py list [C]       every template C can use, with where it comes from
    python3 tools/templates.py use C FILE NAME   switch one cv.html to another template
    python3 tools/templates.py new NAME DEST [FROM]   start a template in DEST/NAME, a copy of FROM

A template is a folder with cv.css and template.json, plus whatever fonts and images it needs,
and optionally layout.html: where the CV's blocks go on the page (see compose()).
A CV links it as `template:<name>/cv.css` and its images as `template:<name>/assets/...`, so the
CV does not care where the template lives. Folders are searched in this order, and the first
template with a given name wins:

1. local/<c>/templates/, then the "templates" list in local/<c>/openvita.json (a person's own,
   or their company's),
2. OPENVITA_TEMPLATES, folders separated by ":" (for example a company's template repository),
3. templates/ in this repository.

Each folder in that list is either one template (it has template.json) or holds several.
"""

import html
import json
import os
import re
import shutil
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402

ROOT = profiles.ROOT
BUILTIN = os.path.join(ROOT, "templates")
SHARED = os.path.join(BUILTIN, "_shared")  # fonts any template may use as ../_shared/fonts/...
DEFAULT = "classic"
MARKUP = "openvita"  # the markup draft.py writes; a template that styles other markup says so in template.json
NAME = re.compile(r"[a-z0-9][\w-]*")
LINK = re.compile(r"template:([\w-]+)/")
CSS = re.compile(r"template:([\w-]+)/cv\.css")
BRAND = re.compile(r"<!-- brand -->.*?<!-- /brand -->", re.S)
# The blocks of the shared markup, as a layout names them. "sidebar" takes both side blocks when a
# layout has no slot of their own; "rest" takes whatever no other slot took.
SLOTS = ("brand", "photo", "header", "profile", "highlight", "sidebar-main", "social", "edu", "experience", "projects")
SLOT_NAMES = SLOTS + ("sidebar", "rest")
SLOT_COMMENT = re.compile(r"<!--\s*slot:\s*([\w\s-]+?)\s*-->")
SLOT_ELEMENT = re.compile(r'<(\w+)\b([^>]*?)\s+data-slot="([\w\s-]+)"([^>]*)>\s*</\1>')
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def search_path(c=""):
    """[(folder, source)] in search order."""
    out = []
    if c:
        try:
            own = os.path.join(profiles.real_dir(c), "templates")
            if os.path.isdir(own):
                out.append((own, f"local/{c}/templates"))
            out += [(profiles.resolve(c, p), f"local/{c}/{profiles.CONFIG}") for p in profiles.config(c).get("templates") or []]
        except ValueError:
            pass
    out += [(os.path.abspath(os.path.expanduser(p)), "OPENVITA_TEMPLATES") for p in os.environ.get("OPENVITA_TEMPLATES", "").split(":") if p]
    out.append((BUILTIN, "built in"))
    return out


def read(folder, source):
    """(template, problem): one of them is None."""
    meta_path = os.path.join(folder, "template.json")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        if not isinstance(meta, dict):
            raise ValueError("not an object")
    except OSError:
        meta = {}
    except ValueError as e:
        return None, f"{meta_path}: {e}"
    name = str(meta.get("name") or os.path.basename(os.path.normpath(folder)))
    if not NAME.fullmatch(name):
        return None, f"{folder}: bad template name {name!r} (lower case letters, digits, - and _)"
    if not os.path.isfile(os.path.join(folder, "cv.css")):
        return None, f"{folder}: no cv.css"
    brand = meta.get("brand") if isinstance(meta.get("brand"), dict) else {}
    markup = str(meta.get("markup") or MARKUP)
    layout = os.path.join(folder, "layout.html")
    return {"name": name, "label": str(meta.get("label") or name), "description": str(meta.get("description") or ""),
            "dir": os.path.realpath(folder), "source": source, "brand": brand, "markup": markup,
            "layout": os.path.realpath(layout) if os.path.isfile(layout) else ""}, None


def discover(c=""):
    """(templates, problems): templates in search order, first of each name; problems as text."""
    found, problems, seen = [], [], set()
    for folder, source in search_path(c):
        if not os.path.isdir(folder):
            if source != "built in":
                problems.append(f"{folder}: not a folder ({source})")
            continue
        if os.path.isfile(os.path.join(folder, "template.json")) or os.path.isfile(os.path.join(folder, "cv.css")):
            candidates = [folder]
        else:
            candidates = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                          if not n.startswith((".", "_")) and os.path.isdir(os.path.join(folder, n))]
        for d in candidates:
            t, problem = read(d, source)
            if problem:
                problems.append(problem)
            elif t["name"] not in seen:
                seen.add(t["name"])
                found.append(t)
    return found, problems


def find(name, c=""):
    return next((t for t in discover(c)[0] if t["name"] == name), None)


def names(c=""):
    return [t["name"] for t in discover(c)[0]]


def current(text):
    m = CSS.search(text)
    return m.group(1) if m else ""


def brand_html(t, person=None):
    """The brand block for template t: the company's logo, name and contact line, from template.json.
    Empty markers when the template has no brand, so switching back and forth keeps working."""
    b = (t or {}).get("brand") or {}
    if not b:
        return "<!-- brand --><!-- /brand -->"
    esc = lambda s: html.escape(str(s), quote=True)
    out = ['<!-- brand -->', '<div class="brand">']
    if b.get("logo"):
        out.append(f'  <img class="brand-logo" src="template:{t["name"]}/{esc(b["logo"])}" alt="{esc(b.get("name", ""))}">')
    if b.get("name"):
        out.append(f'  <p class="brand-name">{esc(b["name"])}</p>')
    if b.get("url"):
        out.append(f'  <p class="brand-url"><a href="{esc(b["url"])}">{esc(re.sub(r"^https?://", "", b["url"]).rstrip("/"))}</a></p>')
    out.append('</div>')
    out.append('<!-- /brand -->')
    return "\n".join(out)


def brand_contact(t, person):
    """Contact details the brand supplies for the person: work email from a pattern, office address."""
    b = (t or {}).get("brand") or {}
    parts = str(person.get("name") or "").lower().split()
    first, last = (parts[0], parts[-1]) if parts else ("", "")
    ascii_ = lambda s: re.sub(r"[^a-z0-9.-]", "", s.replace("æ", "ae").replace("ø", "o").replace("å", "a"))
    email = b.get("email", "").replace("{first}", ascii_(first)).replace("{last}", ascii_(last)) if first else ""
    return {"email": email, "address": b.get("address", ""), "phone": b.get("phone", "")}


def switch(text, t):
    """cv.html text using template t instead: the stylesheet, the brand's images and the brand block."""
    text = LINK.sub(f"template:{t['name']}/", text)
    return BRAND.sub(lambda _: brand_html(t), text, count=1)


def compatible(c, text, t):
    """None when a CV (its text) can move to template t, else why not: templates that style
    different markup cannot be swapped, the content would not fit."""
    cur = find(current(text), c)
    if cur and cur["markup"] != t["markup"]:
        return (f"{t['label']} styles {t['markup']} markup and this CV is written for {cur['markup']} markup "
                f"({cur['label']}); pick a template with the same markup")
    return None


class _Top(HTMLParser):
    """The elements at the top level of an HTML fragment, as [(start, end, classes)] offsets."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text, self.depth, self.nodes, self.start, self.classes = text, 0, [], 0, set()
        self.lines = [0] + [m.end() for m in re.finditer(r"\n", text)]

    def here(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.depth == 0:
            self.start, self.classes = self.here(), set((dict(attrs).get("class") or "").split())
            if tag in VOID:
                self.nodes.append((self.start, self.start + len(self.get_starttag_text()), self.classes))
                return
        if tag not in VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.depth == 0:
            start = self.here()
            self.nodes.append((start, start + len(self.get_starttag_text()), set((dict(attrs).get("class") or "").split())))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        self.depth -= 1
        if self.depth == 0:
            self.nodes.append((self.start, self.text.index(">", self.here()) + 1, self.classes))
        elif self.depth < 0:
            raise ValueError(f"</{tag}> closes nothing")


def block_name(classes):
    for name in ("brand", "photo", "header", "profile", "highlight", "edu", "experience", "projects"):
        if name in classes:
            return name
    if "sidebar" in classes:
        return "social" if "social" in classes else "sidebar-main"
    return ""


def blocks(body):
    """[(name, source)] covering all of body, in order: each top-level element with the comments and
    text before it, and an h2.page-title together with the block it heads. None when the elements
    are not closed properly, as a layout cannot be applied safely then."""
    p = _Top(body)
    try:
        p.feed(body)
        p.close()
    except (ValueError, AssertionError):
        return None
    if p.depth:
        return None
    out, at, title = [], 0, None
    for start, end, classes in p.nodes:
        if "page-title" in classes:
            title = title if title is not None else at
            continue
        begin = title if title is not None else at
        out.append([block_name(classes), body[begin:end]])
        at, title = end, None
    tail = body[at:]
    if tail.strip() or not out:
        out.append(["", tail])
    else:
        out[-1][1] += tail
    return [tuple(b) for b in out]


def layout_slots(layout):
    """The slot names a layout uses, in order."""
    found = [(m.start(), m.group(1).split()) for m in SLOT_COMMENT.finditer(layout)]
    found += [(m.start(), m.group(3).split()) for m in SLOT_ELEMENT.finditer(layout)]
    return [n for _, names in sorted(found) for n in names]


def layout_problems(layout):
    """(errors, warnings) about a layout: unknown slots, slots used twice, blocks it has no place for."""
    used = layout_slots(layout)
    errors = [f"unknown slot {n!r} (slots: {', '.join(SLOT_NAMES)})" for n in dict.fromkeys(used) if n not in SLOT_NAMES]
    errors += [f"slot {n!r} is used more than once" for n in dict.fromkeys(used) if used.count(n) > 1]
    own = set(used)
    placed = lambda n: n in own or (n in ("sidebar-main", "social") and "sidebar" in own)
    missing = [n for n in SLOTS if not placed(n)]
    warnings = [f"no slot for {', '.join(missing)}: " + ("they go in the rest slot" if "rest" in own else "they go after the layout")] if missing else []
    return errors, warnings


def compose(text, layout):
    """The CV text with its body laid out by a template's layout.html. A layout is the body of a page
    with slots where the CV's blocks go: `<!-- slot: header -->`, or an empty element with
    data-slot="header profile" that gets the blocks as its content and is left out when it gets
    none. Blocks no slot takes go in the "rest" slot, or after the layout: nothing in the CV is
    ever dropped. The CV file itself keeps only the content; this runs when it is rendered."""
    start, end = re.search(r"<body[^>]*>", text), text.rfind("</body>")
    if not start or end < start.end():
        return text
    found = blocks(text[start.end():end])
    if found is None:
        return text
    used, own = [False] * len(found), set(layout_slots(layout))

    def wants(slot, name):
        return slot == name or (slot == "sidebar" and name in ("sidebar-main", "social") and name not in own)

    def take(names):
        out = []
        for slot in names:  # in the layout's order; blocks of one slot in the CV's order
            for i, (name, source) in enumerate(found):
                if not used[i] and wants(slot, name):
                    used[i] = True
                    out.append(source)
        return "".join(out)

    marks = sorted([(m.start(), m.end(), m.group(1).split(), None) for m in SLOT_COMMENT.finditer(layout)]
                   + [(m.start(), m.end(), m.group(3).split(), m) for m in SLOT_ELEMENT.finditer(layout)])
    filled = {i: take(names) for i, (_, _, names, _) in enumerate(marks) if "rest" not in names}
    rest = "".join(source for i, (_, source) in enumerate(found) if not used[i])
    rest_at = next((i for i, (_, _, names, _) in enumerate(marks) if "rest" in names), None)
    if rest_at is not None:
        filled[rest_at], rest = rest, ""
    out, at = [], 0
    for i, (s, e, _, m) in enumerate(marks):
        out.append(layout[at:s])
        if m is None:
            out.append(filled[i])
        elif filled[i].strip():
            out.append(f"<{m.group(1)}{m.group(2)}{m.group(4)}>{filled[i]}</{m.group(1)}>")
        at = e
    out.append(layout[at:])
    return text[:start.end()] + "\n" + "".join(out) + rest + "\n" + text[end:]


def laid_out(c, text):
    """The CV text as rendered: laid out by its template's layout.html, when it has one."""
    t = find(current(text), c)
    if not t or not t.get("layout"):
        return text
    with open(t["layout"], encoding="utf-8") as fh:
        return compose(text, fh.read())


def new(name, dest, source=DEFAULT, c=""):
    """A new template in dest/name, copied from template `source`."""
    if not NAME.fullmatch(name):
        raise SystemExit(f"bad template name {name!r} (lower case letters, digits, - and _)")
    t = find(source, c)
    if not t:
        raise SystemExit(f"unknown template {source!r} (see make templates)")
    target = os.path.join(os.path.abspath(os.path.expanduser(dest)), name)
    if os.path.exists(target):
        raise SystemExit(f"{target} already exists")
    shutil.copytree(t["dir"], target)
    meta_path = os.path.join(target, "template.json")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = {}
    meta.update(name=name, label=name.replace("-", " ").capitalize(), description=f"Started from {t['label']}.")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    for f in ("cv.css", "layout.html"):  # a layout links its own images as template:<name>/
        path = os.path.join(target, f)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace(f"template:{t['name']}/", f"template:{name}/"))
    return target


def use(c, path, name):
    t = find(name, c)
    if not t:
        raise SystemExit(f"unknown template {name!r} (see make templates C={c})")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not CSS.search(text):
        raise SystemExit(f"{path} does not link template:<name>/cv.css")
    why = compatible(c, text, t)
    if why:
        raise SystemExit(why)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(switch(text, t))


def main(argv):
    if argv[:1] == ["list"]:
        c = argv[1] if len(argv) > 1 else ""
        found, problems = discover(c)
        for t in found:
            where = os.path.relpath(t["dir"], ROOT) if os.path.commonpath([ROOT, t["dir"]]) == ROOT else t["dir"]
            print(f"{t['name']:<18} {t['label']:<22} {where}  ({t['source']}" + ("" if t["markup"] == MARKUP else f", {t['markup']} markup") + ")")
        for p in problems:
            print(f"problem: {p}", file=sys.stderr)
        return 1 if problems else 0
    if argv[:1] == ["new"] and len(argv) in (3, 4):
        print(new(argv[1], argv[2], *argv[3:]))
        return 0
    if argv[:1] == ["use"] and len(argv) == 4:
        use(argv[1], argv[2], argv[3])
        print(f"{argv[2]} now uses template {argv[3]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
