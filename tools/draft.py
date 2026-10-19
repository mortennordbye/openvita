#!/usr/bin/env python3
"""A first CV straight from the OpenSelf profile, in the shared markup every template styles.

    python3 tools/draft.py C [--variant generic | --app NAME] [--template NAME] [--lang en|nb] [--force]

Writes local/<c>/base/<variant>/cv.html (or applications/<app>/cv.html). The draft is a starting
point: an assistant or the person rewrites it for the reader (guide/writing.md). It refuses to
overwrite a cv.html that was edited after the last draft, unless --force.

What goes in, following the export rules of the OpenSelf spec (sections 5 and 8):
- customers only as the profile allows (`customer_public`, the alias, internal and portfolio work);
  assignments with an `nda` customer are left out,
- the private `reference` section, the owner's own words and the flags are never copied,
- an entry with an `omit` flag keeps its facts (title, period, technology) but none of its
  text, and the wish is left as a comment in the HTML for whoever edits the CV next,
- removed entries (_removed/) are never used.
Every block carries data-entry (and data-section) with the profile id it came from.
"""

import argparse
import hashlib
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402
import templates  # noqa: E402
from openself import index, model, schema  # noqa: E402

TOP_SKILLS = 8
STAMP = re.compile(r"<!-- openvita draft ([0-9a-f]{12}) -->\n")

WORDS = {
    "en": {"skills": "Key skills", "certs": "Certifications", "languages": "Languages", "profile": "Profile",
           "education": "Education", "experience": "Experience", "projects": "Projects", "links": "Links",
           "now": "present", "internal": "internal", "role": "Your title",
           "months": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()},
    "nb": {"skills": "Nøkkelkompetanse", "certs": "Sertifiseringer", "languages": "Språk", "profile": "Profil",
           "education": "Utdanning", "experience": "Erfaring", "projects": "Prosjekter", "links": "Lenker",
           "now": "nå", "internal": "internt", "role": "Din tittel",
           "months": "jan feb mar apr mai jun jul aug sep okt nov des".split()},
}

esc = lambda s: html.escape(str(s), quote=True)


def when(s, w):
    m = re.fullmatch(r"(\d{4})-(\d{2})", s or "")
    return f"{w['months'][int(m.group(2)) - 1]} {m.group(1)}" if m else (s or "")


def period(e, w):
    s, t = e.get("start"), e.get("end")
    if not s:
        return ""
    if t == "ongoing":
        return f"{when(s, w)} – {w['now']}"
    return f"{when(s, w)} – {when(t, w)}" if t and t != s else when(s, w)


def omitted(e):
    """The standing omit wishes on an entry (not resolved)."""
    return [f.text for f in model.flags(e.body)[0] if f.type == "omit" and not f.resolved]


def text_html(md, indent="      "):
    """Markdown paragraphs and bullet lists from a section, as <p> and <ul>. Flag lines are dropped."""
    out, items = [], []

    def flush():
        if items:
            out.append(indent + "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() and "⚑" not in ln]
        para = []
        for ln in lines:
            m = re.match(r"\s*[-*]\s+(.*)", ln)
            if m:
                if para:
                    out.append(indent + "<p>" + inline(" ".join(para)) + "</p>")
                    para = []
                items.append(inline(m.group(1)))
            else:
                flush()
                para.append(ln.strip().lstrip(">").strip())
        flush()
        if para:
            out.append(indent + "<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)


def inline(s):
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", s)


def section_text(e, ids):
    """[(section id, text)] for the wanted sections of an entry, in profile order."""
    return [(s.id, s.text) for s in model.sections(e.body, e.type) if s.id in ids and s.text.strip()]


def entry_body(e, ids):
    wishes = omitted(e)
    if wishes:
        return "\n".join(f"      <!-- omit: {esc(w).replace('--', '- -')} -->" for w in wishes)
    parts = []
    for sid, text in section_text(e, ids):
        parts.append(f'      <div data-section="{sid}">\n{text_html(text, "        ")}\n      </div>')
    return "\n".join(parts)


def customer(e, labels, w, employers):
    if e.get("kind") == "internal":
        return f"{employers.get(e.get('employment'), '')} ({w['internal']})".strip()
    label = index.customer_label(e, labels)
    return "" if label == "?" else label


def entry(e, title, org, date, body, tags):
    out = [f'  <div class="entry" data-entry="{esc(e.id)}">',
           f'    <p class="date">{esc(date)}</p>',
           f'    <h3>{esc(title)}</h3>']
    if org:
        out.append(f'    <p class="org">{esc(org)}</p>')
    if body:
        out.append(f'    <div class="body">\n{body}\n    </div>')
    if tags:
        out.append(f'    <p class="tags">{esc(", ".join(tags))}</p>')
    out.append('  </div>')
    return "\n".join(out)


def build(c, template, lang):
    p = model.load_profile(profiles.profile_dir(c)) if profiles.exists(c) else None
    w = WORDS[lang]
    labels = schema.labels(p.lang if p else lang)
    person = p.entries.get("person") if p else None
    meta = person.meta if person else {}
    name = meta.get("name") or c.replace("-", " ").title()
    contact = templates.brand_contact(template, meta)
    out = ["<!doctype html>", f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">',
           f"<title>CV {esc(name)}</title>", f'<meta name="author" content="{esc(name)}">',
           f'<link rel="stylesheet" href="template:{template["name"]}/cv.css">', "</head>", "<body>", "",
           templates.brand_html(template), ""]

    for photo in ("photo.jpg", "profile.jpg", "photo.png"):
        if os.path.isfile(os.path.join(profiles.person_dir(c), photo)):
            out += [f'<div class="photo"><img src="../../{photo}" alt=""></div>', ""]
            break

    # header
    out.append('<header class="header" data-entry="person">')
    out.append(f'  <h1 class="name">{esc(name)}</h1>')
    out.append(f'  <p class="role">{esc(meta.get("title") or w["role"])}</p>')
    lines = []
    phone = meta.get("phone") or contact["phone"]
    email = contact["email"] or meta.get("email")
    place = contact["address"] or meta.get("location")
    if phone:
        lines.append(f'<p class="phone"><span class="icon fa-phone"></span>{esc(phone)}</p>')
    if email:
        lines.append(f'<p class="email"><span class="icon fa-envelope"></span><a href="mailto:{esc(email)}">{esc(email)}</a></p>')
    if place:
        lines.append(f'<p class="place"><span class="icon fa-marker"></span>{esc(place)}</p>')
    if lines:
        out.append('  <div class="contact">\n    ' + "\n    ".join(lines) + "\n  </div>")
    out += ["</header>", ""]

    # profile text
    if person:
        body = entry_body(person, {"about"})
        if body:
            out += ['<section class="profile" data-entry="person">', f'  <h2 class="section">{w["profile"]}</h2>', body, "</section>", ""]

    # the side column: skills, certifications, languages, links
    side = []
    if p:
        ranked = sorted(index.tech_evidence(p).items(), key=lambda kv: (-len(kv[1][0]), kv[0]))[:TOP_SKILLS]
        if ranked:
            side += [f'  <h2>{w["skills"]}</h2>', '  <ul class="keys">'] + [f"    <li>{esc(t)}</li>" for t, _ in ranked] + ["  </ul>"]
        certs = p.entries.get("certifications")
        rows = [r for r in model.parse_table(certs.body) if r and r[0].strip()] if certs and not omitted(certs) else []
        if rows:
            side += [f'  <h2>{w["certs"]}</h2>', '  <ul class="certs" data-entry="certifications">']
            side += [f'    <li>{esc(r[0])}{" (" + esc(r[2][:4]) + ")" if len(r) > 2 and r[2] else ""}</li>' for r in rows]
            side.append("  </ul>")
    if meta.get("languages"):
        side += [f'  <h2>{w["languages"]}</h2>', '  <ul class="languages">'] + [f"    <li>{esc(x)}</li>" for x in person.list("languages")] + ["  </ul>"]
    if side:
        out += ['<aside class="sidebar main">'] + side + ["</aside>", ""]
    links = [(k, meta.get(k)) for k in ("linkedin", "github") if meta.get(k)] + [("link", x) for x in (person.list("links") if person else [])]
    if links:
        out.append('<aside class="sidebar social">')
        out.append(f'  <h2>{w["links"]}</h2>')
        for kind, url in links:
            shown = re.sub(r"^https?://(www\.)?", "", str(url)).rstrip("/")
            out.append(f'  <p class="{kind}"><span class="icon fa-{kind}"></span><a href="{esc(url)}">{esc(shown)}</a></p>')
        out += ["</aside>", ""]

    # education
    edu = p.entries.get("education") if p else None
    rows = [r for r in model.parse_table(edu.body) if r and r[0].strip()] if edu and not omitted(edu) else []
    if rows:
        out += ['<section class="edu" data-entry="education">', f'  <h2 class="section">{w["education"]}</h2>']
        for r in rows:
            r = (r + ["", "", "", ""])[:4]
            dates = " – ".join(x for x in (r[2], r[3]) if x)
            out += ['  <div class="entry">', f'    <p class="date">{esc(dates)}</p>', f"    <h3>{esc(r[0])}</h3>"]
            if r[1]:
                out.append(f'    <p class="org">{esc(r[1])}</p>')
            out.append("  </div>")
        out += ["</section>", ""]

    if p:
        jobs = index.newest_first(p.of_type("employment"))
        employers = {e.id: e.get("employer") or "" for e in jobs}
        if jobs:
            out += [f'<h2 class="page-title">{w["experience"]}</h2>', '<section class="timeline experience">']
            for e in jobs:
                out.append(entry(e, e.get("title") or "", e.get("employer") or "", period(e, w),
                                 entry_body(e, {"summary"}), e.list("tech")))
            out += ["</section>", ""]
        work = [e for e in index.newest_first(p.of_type("assignment")) if e.get("customer_public") != "nda"]
        if work:
            out += [f'<h2 class="page-title">{w["projects"]}</h2>', '<section class="timeline projects">']
            for e in work:
                out.append(entry(e, e.get("role") or "", customer(e, labels, w, employers), period(e, w),
                                 entry_body(e, {"summary", "challenge", "contribution", "outcome"}), e.list("tech")))
            out += ["</section>", ""]

    out += ["</body>", "</html>", ""]
    return "\n".join(out)


def stamp(text):
    return f"<!-- openvita draft {hashlib.sha256(text.encode()).hexdigest()[:12]} -->\n" + text


def edited(path):
    """True when path exists and is not exactly the last draft written there."""
    try:
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    except OSError:
        return False
    m = STAMP.match(old)
    return not m or hashlib.sha256(old[m.end():].encode()).hexdigest()[:12] != m.group(1)


def target(c, variant="generic", app=""):
    return os.path.join(profiles.person_dir(c), *(("applications", app) if app else ("base", variant)), "cv.html")


def write(c, variant="generic", app="", template="", lang="", force=False):
    path = target(c, variant, app)
    if os.path.exists(path) and edited(path) and not force:
        raise SystemExit(f"{path} was edited after the last draft; use --force (FORCE=1) to replace it")
    if not template and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            template = templates.current(fh.read())
    name = template or profiles.config(c).get("template") or templates.DEFAULT
    t = templates.find(name, c)
    if not t:
        raise SystemExit(f"unknown template {name!r} (see make templates C={c})")
    text = stamp(build(c, t, lang if lang in WORDS else profiles.language(c)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def switch(c, path, name):
    """Move one cv.html to template `name`. An untouched draft is drafted again in the new template,
    so the brand's contact details follow; anything edited keeps its text (templates.use)."""
    if not templates.find(name, c):
        raise SystemExit(f"unknown template {name!r} (see make templates C={c})")
    if os.path.isfile(path) and not edited(path):
        parts = os.path.relpath(path, profiles.person_dir(c)).split(os.sep)
        if len(parts) == 3 and parts[0] in ("base", "applications"):
            with open(path, encoding="utf-8") as fh:
                lang = (re.search(r'<html lang="(\w+)"', fh.read()) or [None, ""])[1]
            kw = {"app": parts[1]} if parts[0] == "applications" else {"variant": parts[1]}
            return write(c, template=name, lang=lang, force=True, **kw)
    templates.use(c, path, name)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("c")
    ap.add_argument("--variant", default="generic")
    ap.add_argument("--app", default="")
    ap.add_argument("--template", default="")
    ap.add_argument("--lang", default="", choices=["", *WORDS])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--switch", metavar="FILE", help="only move FILE to --template (see switch())")
    a = ap.parse_args(argv)
    if a.switch:
        print(f"{switch(a.c, a.switch, a.template)} now uses template {a.template}")
        return 0
    print(write(a.c, a.variant, a.app, a.template, a.lang, a.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
