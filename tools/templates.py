#!/usr/bin/env python3
"""CV templates: where they are found, and how a CV refers to them (see TEMPLATES.md).

    python3 tools/templates.py list [C]       every template C can use, with where it comes from
    python3 tools/templates.py use C FILE NAME   switch one cv.html to another template

A template is a folder with cv.css and template.json, plus whatever fonts and images it needs.
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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402

ROOT = profiles.ROOT
BUILTIN = os.path.join(ROOT, "templates")
SHARED = os.path.join(BUILTIN, "_shared")  # fonts any template may use as ../_shared/fonts/...
DEFAULT = "classic"
NAME = re.compile(r"[a-z0-9][\w-]*")
LINK = re.compile(r"template:([\w-]+)/")
CSS = re.compile(r"template:([\w-]+)/cv\.css")
BRAND = re.compile(r"<!-- brand -->.*?<!-- /brand -->", re.S)


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
    return {"name": name, "label": str(meta.get("label") or name), "description": str(meta.get("description") or ""),
            "dir": os.path.realpath(folder), "source": source, "brand": brand}, None


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


def use(c, path, name):
    t = find(name, c)
    if not t:
        raise SystemExit(f"unknown template {name!r} (see make templates C={c})")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not CSS.search(text):
        raise SystemExit(f"{path} does not link template:<name>/cv.css")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(switch(text, t))


def main(argv):
    if argv[:1] == ["list"]:
        c = argv[1] if len(argv) > 1 else ""
        found, problems = discover(c)
        for t in found:
            where = os.path.relpath(t["dir"], ROOT) if os.path.commonpath([ROOT, t["dir"]]) == ROOT else t["dir"]
            print(f"{t['name']:<18} {t['label']:<22} {where}  ({t['source']})")
        for p in problems:
            print(f"problem: {p}", file=sys.stderr)
        return 1 if problems else 0
    if argv[:1] == ["use"] and len(argv) == 4:
        use(argv[1], argv[2], argv[3])
        print(f"{argv[2]} now uses template {argv[3]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
