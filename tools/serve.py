#!/usr/bin/env python3
"""Live CV workbench in the browser.

    make serve [C=kari] [VARIANT=generic | APP=2026-10-acme-platform] [PORT=8000]

A small local app (127.0.0.1 only): a folder list on the left with every person in local/, their
base CVs (base/<variant>) and their applications (applications/), and the selected CV on the right
as real PDF text you can select, copy and search. It watches cv.html, the CSS and assets of every
template the person can use and their photos, rebuilds the selected CV on every save and swaps the
new pages in without losing your scroll position. Rebuilds go through a warm WeasyPrint kept running
in Docker (tools/render.py and tools/render-worker.py, about 0.25 s per build).
job-ad.md and notes.md open as extra tabs, and so does each Word form in the application's forms/
(filled from forms/<form>.json with tools/fill-docx.py, rendered to PDF by LibreOffice in the same
Docker image). The clock button lists the saved revisions of the selected CV (the person's folder
is its own git repository), shows any of them as a PDF, and the save button takes a new revision
(`make save`). The Profile view mounts OpenSelf's own UI (openself/openself/web/static/app.js) on
the person's profile (tools/profiles.py). Select text anywhere (CV, job ad, notes, profile) and a
small box opens: what you write there is stored in local/<name>/feedback.json for an assistant
such as Claude Code to pick up, see "Feedback from the workbench" in AGENTS.md. The Instructions
view shows what the assistant works from (AGENTS.md, the guides and the person's tuning.md).

The flow: "New application" creates one from the base CV with the pasted job ad, "Tailor CV" queues
a request in feedback.json (kind "generate"), the assistant tailors the CV from the instructions,
the ad and the profile, then every comment you make is kept (never deleted) and the lessons from
them are distilled into local/<name>/tuning.md, which is part of the instructions next time.
"Draft from profile" rebuilds a CV straight from the profile (tools/draft.py) as long as nobody
edited it since the last draft.

The UI speaks English or Norwegian (bokmål), following the person's CV language
(local/<name>/openvita.json, else the profile's first language).

PDF rendering uses the vendored pdf.js in tools/vendor/pdfjs (Apache-2.0), no network needed.
"""
import glob
import importlib.util
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft  # noqa: E402  a CV straight from the profile
import profiles  # noqa: E402  each person's OpenSelf profile
import profile_api  # noqa: E402  the Profile endpoints
import render  # noqa: E402  HTML to PDF in Docker
import templates  # noqa: E402  where templates are found
from openself import model as pmodel  # noqa: E402
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "tools", "vendor")
STATIC = os.path.join(ROOT, "tools", "static")  # the Profile view: profile.js and profile.css
OPENSELF_STATIC = os.path.join(ROOT, "openself", "openself", "web", "static")  # OpenSelf's UI, mounted for Profile
LOCAL = profiles.LOCAL  # one folder per person on this machine, gitignored
START_C = sys.argv[1] if len(sys.argv) > 1 else ""
START_VARIANT = sys.argv[2] if len(sys.argv) > 2 else ""
START_APP = sys.argv[3] if len(sys.argv) > 3 else ""
PORT = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else 8000

# Child `make` calls must not inherit the variables this server was started with (make serve
# APP=x exports APP=x through MAKEFLAGS, and then every build would be for x).
CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES")}

# Messages the server sends back, in the person's language.
SAY = {
    "en": {"no-profile": "no profile", "no-entry": "entry not found", "queued": "Already requested, waiting for the assistant",
           "interview": "Requested. The assistant asks you in its session when it picks this up.",
           "interview-default": "Interview me about this entry", "unknown-person": "unknown person",
           "saved": "Revision saved", "unchanged": "No changes since the last revision", "not-saved": "Could not save",
           "name-or-ad": "name or job ad missing", "unknown-template": "unknown template", "same-template": "Already uses this template",
           "switched": "Switched to {tpl}. The previous version is saved as a revision.", "not-switched": "Could not switch template",
           "only-apps": "Only applications with a job ad can be tailored", "requested": "Requested. The assistant tailors the CV, the page updates when it is done.",
           "generate": "Tailor the CV to this job ad", "ad": "the job ad in job-ad.md", "no-pdf": "PDF not found. Wait until it is built.",
           "drafted": "Drafted from the profile. The previous version is saved as a revision.", "macos": "Only available on macOS"},
    "nb": {"no-profile": "ingen profil", "no-entry": "fant ikke oppføringen", "queued": "Allerede bestilt, venter på assistenten",
           "interview": "Bestilt. Assistenten spør deg i økten sin når den tar dette.",
           "interview-default": "Intervju meg om denne oppføringen", "unknown-person": "ukjent person",
           "saved": "Revisjon lagret", "unchanged": "Ingen endringer siden forrige revisjon", "not-saved": "Kunne ikke lagre",
           "name-or-ad": "navn eller annonse mangler", "unknown-template": "ukjent mal", "same-template": "Bruker allerede denne malen",
           "switched": "Byttet til {tpl}. Forrige versjon er lagret som revisjon.", "not-switched": "Kunne ikke bytte mal",
           "only-apps": "Bare søknader med annonse kan skreddersys", "requested": "Bestilt. Assistenten skreddersyr CV-en, siden oppdateres når den er ferdig.",
           "generate": "Skreddersy CV-en til denne annonsen", "ad": "annonsen i job-ad.md", "no-pdf": "Fant ikke PDF-filen. Vent til den er bygget.",
           "drafted": "Laget fra profilen. Forrige versjon er lagret som revisjon.", "macos": "Bare på macOS"},
}


def lang_of(c):
    try:
        return profiles.language(c)
    except ValueError:
        return "en"


def say(c, key, **kw):
    return SAY[lang_of(c) if c else "en"][key].format(**kw)


def run_make(args):
    return subprocess.run(["make"] + args, cwd=ROOT, capture_output=True, text=True, env=CLEAN_ENV)


def render_pdf(c, src_abs, out_abs):
    """HTML to PDF under build_lock: warm worker first, a one-off container if it fails."""
    return render.pdf(c, src_abs, out_abs, warm=True)


states = {}  # target -> {version, building, error, built}
lock = threading.Lock()
build_lock = threading.Lock()
active = {"key": ""}
recent = {}  # target -> last time a browser asked about it


# A target is "<person>/<path>", where path is base/<variant> or applications/<case>.
def parse(k):
    c, _, path = k.partition("/")
    return c, path


def valid(k):
    c, path = parse(k)
    return bool(re.fullmatch(r"[\w.-]+", c)) and bool(re.fullmatch(r"(base|applications)/[\w.-]+", path))


def case_dir(k):
    c, path = parse(k)
    return os.path.join(LOCAL, c, path)


def src(k):
    return os.path.join(case_dir(k), "cv.html")


def pdf_path(k):
    c, path = parse(k)
    return os.path.join(ROOT, "build", c, path, f"{c}-{path.split('/', 1)[1]}.pdf")


_stats = {}


def profile_stats(c):
    """{employments, assignments, questions} of C's profile, cached for ten seconds."""
    hit = _stats.get(c)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    val = None
    if profiles.exists(c):
        try:
            p = pmodel.load_profile(profiles.profile_dir(c))
            val = {"employments": len(p.of_type("employment")), "assignments": len(p.of_type("assignment")),
                   "questions": sum(1 for e in p.entries.values() for fl in pmodel.flags(e.body)[0] if fl.open)}
        except (OSError, ValueError):
            val = None
    _stats[c] = (time.time(), val)
    return val


def tree():
    out = []
    base = LOCAL
    for c in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if c in profiles.RESERVED or not os.path.isdir(os.path.join(base, c)):
            continue

        def names(sub, order=False):
            d = os.path.join(base, c, sub)
            if not os.path.isdir(d):
                return []
            found = [n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "cv.html"))]
            return sorted(found, reverse=order, key=(lambda n: (n != "generic", n)) if sub == "base" else None)
        generic, cases = names("base"), names("applications", True)
        profile = "profile" if profiles.exists(c) else ""
        if generic or cases or profile or os.path.isfile(os.path.join(base, c, profiles.CONFIG)):
            out.append({"person": c, "base": generic, "apps": cases, "profile": profile, "lang": lang_of(c),
                        "stats": profile_stats(c)})
    return out


def watched(k):
    c, _ = parse(k)
    d = os.path.join(LOCAL, c)
    files = [src(k)] + glob.glob(os.path.join(templates.SHARED, "*.css"))
    for t in templates.discover(c)[0]:
        files += [f for f in glob.glob(os.path.join(t["dir"], "**", "*"), recursive=True) if os.path.isfile(f)]
    files += glob.glob(os.path.join(d, "*.jpg")) + glob.glob(os.path.join(d, "*.png"))
    return files


def stamp(k):
    out = []
    for f in watched(k):
        try:
            out.append((f, os.stat(f).st_mtime_ns))
        except OSError:
            pass
    return out


def state_of(k):
    return states.setdefault(k, {"version": 0, "building": False, "error": "", "built": ""})


def build(k):
    with build_lock:
        with lock:
            state_of(k)["building"] = True
        t0 = time.time()
        before = os.path.getmtime(pdf_path(k)) if os.path.isfile(pdf_path(k)) else 0
        ok, err = render_pdf(parse(k)[0], src(k), pdf_path(k))
        ok = ok and os.path.isfile(pdf_path(k)) and os.path.getmtime(pdf_path(k)) > before
        with lock:
            s = state_of(k)
            s["building"] = False
            s["version"] += 1
            if ok:
                s["error"] = ""
                s["built"] = time.strftime("%H:%M:%S")
                print(f"built {k} in {time.time() - t0:.1f}s", flush=True)
            else:
                s["error"] = err or "build failed"
                print(f"build failed for {k}", flush=True)


def start_build(k):
    state_of(k)["building"] = True
    threading.Thread(target=build, args=(k,), daemon=True).start()


def select(k):
    """Make k the watched CV and build it if there is no PDF yet or the sources are newer."""
    if not valid(k) or not os.path.isfile(src(k)):
        return False
    active["key"] = k
    recent[k] = time.time()
    p = pdf_path(k)
    stale = not os.path.isfile(p) or any(m > os.stat(p).st_mtime_ns for _, m in stamp(k))
    if stale and not state_of(k)["building"]:
        start_build(k)
    elif not stale and state_of(k)["version"] == 0:
        with lock:
            s = state_of(k)
            s["version"] = 1
            s["built"] = time.strftime("%H:%M:%S", time.localtime(os.stat(p).st_mtime))
    return True


def watcher():
    """Rebuild every CV that a browser tab asked about in the last 15 seconds when its sources change."""
    last = {}
    while True:
        time.sleep(0.25)
        now_t = time.time()
        for k in [k for k, t in list(recent.items()) if now_t - t < 15]:
            now = stamp(k)
            if k not in last:
                last[k] = now
            elif now != last[k]:
                time.sleep(0.15)  # let the editor finish writing
                last[k] = stamp(k)
                if not state_of(k)["building"]:
                    start_build(k)


# ---- revisions: the person's folder is its own git repo -----------------------------------
def git(c, *args):
    return subprocess.run(["git", "-C", os.path.join(LOCAL, c)] + list(args),
                          capture_output=True, text=True)


def history(k):
    """[(hash, path_at_that_commit, epoch, subject)] for the CV, following renames."""
    c, path = parse(k)
    r = git(c, "log", "--follow", "-n", "60", "--name-status", "--format=@@%h%x00%ct%x00%s", "--", f"{path}/cv.html")
    items, cur = [], None
    for line in r.stdout.splitlines():
        if line.startswith("@@"):
            h, ct, subj = line[2:].split("\x00", 2)
            cur = {"hash": h, "time": int(ct), "subject": subj, "path": f"{path}/cv.html"}
            items.append(cur)
        elif line.strip() and cur is not None and "path_set" not in cur:
            cur["path"] = line.split("\t")[-1]
            cur["path_set"] = True
    return items


_dirty = {}


def is_dirty(k):
    """Unsaved changes to the CV, cached for two seconds because the page asks several times a second."""
    c, path = parse(k)
    hit = _dirty.get(k)
    if hit and time.time() - hit[0] < 2:
        return hit[1]
    val = bool(git(c, "status", "--porcelain", "--", f"{path}/cv.html").stdout.strip())
    _dirty[k] = (time.time(), val)
    return val


def revisions(k):
    c, path = parse(k)
    items = history(k)
    for it in items:
        it["tags"] = []
        it.pop("path_set", None)
    # Releases (make release) are empty commits with a vN tag. Attach each tag to the newest
    # revision of this CV at or before it. Tags that name a customer case belong to that case only.
    cases = [n for n in os.listdir(os.path.join(LOCAL, c, "applications"))] \
        if os.path.isdir(os.path.join(LOCAL, c, "applications")) else []
    kind, name = path.split("/", 1)
    r = git(c, "for-each-ref", "refs/tags", "--format=%(refname:short)")
    for tag in r.stdout.split():
        named = [a for a in cases if a in tag]
        if (kind == "applications" and name not in named) or (kind == "base" and named):
            continue
        for it in items:
            if git(c, "merge-base", "--is-ancestor", it["hash"], f"{tag}^{{commit}}").returncode == 0:
                it["tags"].append(tag)
                break
    dirty = bool(git(c, "status", "--porcelain", "--", f"{path}/cv.html").stdout.strip())
    return {"dirty": dirty, "items": items}


def rev_pdf(k, h):
    """Render an old revision of the CV to build/<c>/<path>/.rev/<hash>.pdf and return the file."""
    c, path = parse(k)
    match = next((i for i in history(k) if i["hash"] == h), None)
    if not match:
        return None
    out = os.path.join(ROOT, "build", c, path, ".rev", f"{h}.pdf")
    if os.path.isfile(out):
        return out
    html = git(c, "show", f"{h}:{match['path']}").stdout
    if not html:
        return None
    with build_lock:
        render.pdf_text(c, html, case_dir(k), out, warm=True)
    return out if os.path.isfile(out) else None


def read_text(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read().rstrip()
    except OSError:
        return "(missing)"


def demote(md, by=2):
    """Push the headings of an included file down so the file's own title is not another top heading."""
    out, fenced = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = re.match(r"(#{1,6})\s", line)
        out.append(("#" * min(6, len(m.group(1)) + by) + line[len(m.group(1)):]) if m and not fenced else line)
    return "\n".join(out)


def sections(intro, files):
    out = [intro, ""] + [f"- `{f}` ({what})" for f, what in files]
    for f, _ in files:
        out.append(f"\n---\n\n# `{f}`\n\n{demote(read_text(f))}")
    return "\n".join(out) + "\n"


DOC_RE = re.compile(r"doc/(how|prompt)|[\w.-]+/(raw|personal)")


PROMPT_FILES = [("AGENTS.md", "the project: build, rules for facts and contact details, workflow"),
                ("guide/writing.md", "how CVs are written"),
                ("guide/profile.md", "how the profile is read and filled in"),
                ("TEMPLATES.md", "what a template is and the markup every template styles"),
                ("openself/SPEC.md", "the profile format")]


def personal_files(c):
    return [(f"local/{c}/AGENTS.md", "your standing wishes"),
            (f"local/{c}/tuning.md", "what the assistant has learned from your feedback")]


def doc_files(t):
    """Repo-relative paths of the files behind a non-CV view."""
    if t == "doc/how":
        return ["tools/how-it-works.html"]
    if t == "doc/prompt":
        return [f for f, _ in PROMPT_FILES]
    c, kind = t.split("/")
    return profile_files(c) if kind == "raw" else [f for f, _ in personal_files(c)]


def profile_files(c):
    """The files behind the Profile view: the profile's index and entries."""
    if not profiles.exists(c):
        return []
    p = profiles.profile_dir(c)
    shown = os.path.relpath(p, ROOT) if os.path.commonpath([ROOT, p]) == ROOT else p
    return [f"{shown}/{rel}" for rel in ["INDEX.md"] + pmodel.profile_files(p)]


def cv_files(t, source="cv"):
    """Repo-relative paths behind a CV view: cv.html, or the job ad, notes or a form tab."""
    c, path = parse(t)
    if source.startswith("form:") and re.fullmatch(r"form:[\w .-]+", source):
        return [f"local/{c}/{path}/forms/{source[5:]}.json"]
    return [f"local/{c}/{path}/{source if source in ('job-ad.md', 'notes.md') else 'cv.html'}"]


_spec = importlib.util.spec_from_file_location("fill_docx", os.path.join(ROOT, "tools", "fill-docx.py"))
fill_docx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fill_docx)


def forms(t):
    """Names (without .docx) of the customer forms in a case's forms/ folder."""
    d = os.path.join(case_dir(t), "forms")
    return sorted(n[:-5] for n in os.listdir(d) if n.endswith(".docx") and re.fullmatch(r"[\w .-]+", n[:-5])) \
        if os.path.isdir(d) else []


def form_docx(t, name):
    """The filled form, refilled when its answers or the original are newer than the output."""
    c, path = parse(t)
    orig = os.path.join(case_dir(t), "forms", name + ".docx")
    answers = os.path.join(case_dir(t), "forms", name + ".json")
    out = os.path.join(ROOT, "build", c, path, name + ".docx")
    if not os.path.isfile(answers):
        return orig
    newest = max(os.path.getmtime(orig), os.path.getmtime(answers))
    if not os.path.isfile(out) or os.path.getmtime(out) < newest:
        try:
            fill_docx.fill(Path(orig), Path(answers), Path(out))
        except SystemExit as e:
            raise ValueError(str(e))
    return out


form_lock = threading.Lock()


def form_pdf(t, name):
    """The filled form as PDF, rendered by LibreOffice when the .docx is newer."""
    docx = form_docx(t, name)
    c, path = parse(t)
    outdir = os.path.join(ROOT, "build", c, path)
    out = os.path.join(outdir, name + ".pdf")
    with form_lock:
        if not os.path.isfile(out) or os.path.getmtime(out) < os.path.getmtime(docx):
            os.makedirs(outdir, exist_ok=True)
            r = subprocess.run(render.docker_args({ROOT: "/work"}) + ["soffice", "-env:UserInstallation=file:///tmp/lo",
                                "--headless", "--convert-to", "pdf", "--outdir", os.path.relpath(outdir, ROOT),
                                os.path.relpath(docx, ROOT)], capture_output=True, text=True)
            if r.returncode or not os.path.isfile(out) or os.path.getmtime(out) < os.path.getmtime(docx):
                raise ValueError((r.stderr or r.stdout).strip()[-1500:] or "LibreOffice gave no PDF")
    return out


def doc_view(t):
    """Views that are not a CV: shared docs, the person's profile and personal instructions."""
    files = doc_files(t)
    if t == "doc/how":
        with open(os.path.join(ROOT, "tools", "how-it-works.html")) as fh:
            return {"type": "html", "body": fh.read(), "files": files}
    if t == "doc/prompt":
        return {"type": "md", "files": files, "body": sections(
            "Shared by everyone. These are the instructions an assistant reads before it changes a CV. Sources, in order:",
            PROMPT_FILES)}
    c, kind = t.split("/")
    if kind == "raw":
        return {"type": "md", "files": files, "body": ""}  # shown by OpenSelf's UI (static/profile.js)
    return {"type": "md", "files": files, "body": sections(
        f"Only for {c}. The assistant reads this together with the shared instructions:", personal_files(c))}


def template_list(c, current=""):
    """[{name, label, description, source, markup}] for the templates this person can use; with the
    CV's current template, only those that style the same markup (the others cannot take its content)."""
    found = templates.discover(c)[0]
    cur = next((t for t in found if t["name"] == current), None)
    return [{k: t[k] for k in ("name", "label", "description", "source", "markup")} for t in found
            if not cur or t["markup"] == cur["markup"]]


def tpl_preview(k, name):
    """Page 1 of this CV rendered in template `name`, as a small PNG (build/<c>/<path>/.tpl/<name>.png)."""
    c, path = parse(k)
    t = templates.find(name, c)
    if not t or not os.path.isfile(src(k)):
        return None
    out = os.path.join(ROOT, "build", c, path, ".tpl", f"{name}.png")
    newest = max([m for _, m in stamp(k)] or [0])
    if os.path.isfile(out) and os.stat(out).st_mtime_ns >= newest:
        return out
    with open(src(k), encoding="utf-8") as fh:
        html = templates.switch(fh.read(), t)
    pdf = out[:-4] + ".pdf"
    with build_lock:
        ok, _ = render.pdf_text(c, html, case_dir(k), pdf, warm=True)
        if ok:
            render.png(pdf, out[:-4], dpi=72, first_only=True)
    return out if os.path.isfile(out) else None


def current_template(k):
    try:
        with open(src(k), encoding="utf-8") as fh:
            return templates.current(fh.read())
    except OSError:
        return ""


def feedback_path(c):
    return os.path.join(LOCAL, c, "feedback.json")


def load_feedback(c):
    try:
        with open(feedback_path(c)) as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def store_feedback(c, items):
    tmp = feedback_path(c) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, feedback_path(c))


fb_lock = threading.Lock()


def current_pdf(k, r=""):
    """The PDF file shown for target k: the current build, or an already rendered old revision."""
    if r:
        c, path = parse(k)
        f = os.path.join(ROOT, "build", c, path, ".rev", f"{r}.pdf")
    else:
        f = pdf_path(k)
    return f if os.path.isfile(f) else None


def save_revision(c, message):
    """Returns (ok, changed). `make save` makes no commit when nothing changed."""
    before = git(c, "rev-parse", "HEAD").stdout.strip()
    r = run_make(["save", f"C={c}", f"MSG={message}"])
    return r.returncode == 0, git(c, "rev-parse", "HEAD").stdout.strip() != before


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#6aa4f8"/>'
           '<path d="M9 9h14M9 14h14M9 19h9" stroke="#0b1220" stroke-width="2.6" stroke-linecap="round"/></svg>')

ICONS = """
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/></symbol>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></symbol>
<symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></symbol>
<symbol id="i-case" viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-save" viewBox="0 0 24 24"><path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v6h8V3M7 21v-7h10v7"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></symbol>
<symbol id="i-open" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></symbol>
<symbol id="i-ad" viewBox="0 0 24 24"><path d="M4 5h16v11H8l-4 4z"/><path d="M8 9h8M8 12h5"/></symbol>
<symbol id="i-note" viewBox="0 0 24 24"><path d="M5 4h14v16H5z"/><path d="M9 9h6M9 13h6M9 17h3"/></symbol>
<symbol id="i-tag" viewBox="0 0 24 24"><path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.2"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></symbol>
<symbol id="i-data" viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></symbol>
<symbol id="i-chat" viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></symbol>
<symbol id="i-spark" viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18 16l.8 2.2L21 19l-2.2.8L18 22l-.8-2.2L15 19l2.2-.8z"/></symbol>
<symbol id="i-archive" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10h14V9M10 13h4"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-help" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/></symbol>
<symbol id="i-layout" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M9 10h12"/></symbol>
<symbol id="i-back" viewBox="0 0 24 24"><path d="M10 6l-6 6 6 6M4 12h16"/></symbol>
</defs></svg>"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>OpenVita</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="stylesheet" href="/vendor/pdfjs/pdf_viewer.min.css">
<link rel="stylesheet" href="/openself/app.css">
<link rel="stylesheet" href="/static/profile.css">
<style>
  /* OpenSelf's palette (openself/openself/web/static/app.css), so the two read as one app. */
  :root { color-scheme: dark; --bg: #1f1f23; --panel: #17171a; --line: #303036; --fg: #e6e6ea; --mut: #8e8e98;
          --acc: #6aa4f8; --acc2: #3fc1a5; --hl: rgba(106,164,248,.16); --hover: rgba(230,230,234,.07);
          --warn: #f0ad4e; --bad: #e5534b; --ok: #4caf50; }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { height: 100%; margin: 0; }
  /* Layout: a header across, then the person's list, the CV, and a rail with comments and templates. */
  body { display: grid; grid-template: "top top top" 56px "side main rail" 1fr / 264px minmax(0, 1fr) 320px;
         height: 100vh; background: var(--bg); color: var(--fg); font: 13px/1.4 -apple-system, system-ui, sans-serif; }
  svg.i { width: 16px; height: 16px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.7;
          stroke-linecap: round; stroke-linejoin: round; }
  #top { grid-area: top; display: flex; align-items: center; gap: 12px; padding: 0 18px; background: var(--panel);
         border-bottom: 1px solid var(--line); min-width: 0; position: relative; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 14px; white-space: nowrap; }
  .logo { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; background: var(--acc);
          color: #0b1220; font-size: 11px; font-weight: 800; }
  #nav { display: flex; gap: 2px; margin-left: 14px; min-width: 0; overflow: hidden; }
  .nv { display: inline-flex; align-items: center; gap: 6px; background: none; border: 0; color: var(--mut); padding: 7px 12px;
        border-radius: 6px; font: inherit; font-size: 13.5px; cursor: pointer; white-space: nowrap; }
  .nv:hover { color: var(--fg); background: var(--hover); } .nv.on { color: #fff; background: var(--hover); font-weight: 600; }
  .nv .badge { background: color-mix(in srgb, var(--warn) 18%, var(--panel)); color: color-mix(in srgb, var(--warn) 75%, var(--fg)); }
  #who { display: flex; align-items: center; gap: 8px; background: var(--panel); border: 1px solid var(--line); color: var(--fg);
         border-radius: 99px; padding: 3px 10px 3px 3px; font: inherit; cursor: pointer; white-space: nowrap; text-transform: capitalize; }
  #who:hover { background: var(--hover); }
  .av { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; color: #0b1220; font-weight: 700;
        font-size: 11px; background: linear-gradient(135deg, var(--acc), var(--acc2)); text-transform: uppercase; }
  #people { right: 18px; top: calc(100% - 6px); min-width: 220px; }
  aside { overflow: auto; background: var(--panel); }
  #side { grid-area: side; border-right: 1px solid var(--line); padding: 14px 12px; display: flex; flex-direction: column; gap: 2px; }
  #rail { grid-area: rail; border-left: 1px solid var(--line); padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  #main { grid-area: main; display: grid; grid-template-rows: auto auto 1fr; min-width: 0; min-height: 0; }
  .grp { display: flex; align-items: center; gap: 7px; margin: 14px 8px 4px; color: var(--mut); font-size: 11px;
         letter-spacing: .07em; text-transform: uppercase; }
  .grp:first-child { margin-top: 4px; }
  .item { display: flex; align-items: center; gap: 9px; width: 100%; text-align: left; background: none; border: 0;
          color: var(--fg); padding: 8px; border-radius: 6px; cursor: pointer; font: inherit; }
  .item.two { flex-direction: column; align-items: flex-start; gap: 2px; }
  .item.two small { margin-left: 0; }
  .health { margin-top: auto; border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: var(--bg);
            text-align: left; color: var(--fg); font: inherit; cursor: pointer; display: flex; flex-direction: column; gap: 4px; }
  .health:hover { border-color: #4a4a52; } .health b { font-size: 13px; margin-bottom: 4px; }
  .health span { color: var(--mut); } .health .q { color: color-mix(in srgb, var(--warn) 75%, var(--fg)); }
  .rh { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; margin: 0; }
  .rh small { margin-left: auto; color: var(--mut); font-weight: 400; font-size: 12px; }
  #cmlist { display: flex; flex-direction: column; gap: 8px; }
  #cmlist .cm { border: 1px solid var(--line); border-radius: 10px; background: var(--bg); padding: 10px 12px; }
  #cmlist .cm + .cm { border-top: 1px solid var(--line); }
  #cmlist .cm .q { white-space: normal; }
  #tplsec { margin-top: 10px; display: flex; flex-direction: column; gap: 10px; }
  #cmbtn { display: none; }
  .item:hover { background: #232328; }
  .item.on { background: var(--hl); color: #fff; }
  .item.on svg { color: var(--acc); }
  .item span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item small { margin-left: auto; color: var(--mut); font-size: 11px; white-space: nowrap; flex: none; }
  .bar { display: flex; gap: 8px; align-items: center; padding: 8px 14px; border-bottom: 1px solid var(--line);
         background: var(--panel); position: relative; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ok); flex: none; }
  .dot.busy { background: var(--warn); } .dot.err { background: var(--bad); }
  #msg { color: var(--mut); margin-right: 6px; white-space: nowrap; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 99px; border: 1px solid var(--warn); color: var(--warn); white-space: nowrap; }
  .btn { display: inline-flex; align-items: center; gap: 6px; background: var(--panel); border: 1px solid var(--line);
         color: var(--fg); padding: 6px 12px; border-radius: 6px; cursor: pointer; font: inherit; text-decoration: none; white-space: nowrap; }
  .btn:hover { background: var(--hover); }
  .btn.on { background: var(--acc); border-color: var(--acc); color: #0b1220; }
  .sp { flex: 1; }
  /* The toolbar over the CV: what you look at, its state, what you can do. Narrow: icons only. */
  #bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 18px; border-bottom: 1px solid var(--line);
         position: relative; container-type: inline-size; min-width: 0; }
  #bar .btn, #tabs { flex: none; }
  .state { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--mut); white-space: nowrap; }
  @container (max-width: 1100px) { #bar #pathbar { display: none; } }
  @container (max-width: 640px) { #bar .btn:not(.primary) .lbl { display: none; } }
  .btn.primary { background: var(--acc); border-color: var(--acc); color: #0b1220; font-weight: 600; }
  .btn.primary:hover { background: color-mix(in srgb, var(--acc) 85%, #fff); }
  .btn.second { border-color: color-mix(in srgb, var(--acc2) 60%, var(--line)); color: color-mix(in srgb, var(--acc2) 80%, var(--fg)); }
  .btn.ghost { border-color: transparent; color: var(--mut); } .btn.ghost:hover { color: var(--fg); }
  .pip { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); margin-left: 2px; }
  #savebtn:has(.pip:not([hidden])) { border-color: color-mix(in srgb, var(--ok) 60%, transparent); background: color-mix(in srgb, var(--ok) 14%, transparent); }
  #pathbar { display: flex; flex: 1 1 auto; gap: 2px; align-items: center; min-width: 0; overflow: hidden; margin-left: 6px; }
  #pathbar .p { display: inline-flex; align-items: center; gap: 5px; background: none; border: 0; color: var(--mut); cursor: pointer;
                padding: 3px 7px; border-radius: 5px; font: 12px ui-monospace, Menlo, monospace; white-space: nowrap; min-width: 0; flex: 0 1 auto; }
  #pathbar .p span { overflow: hidden; text-overflow: ellipsis; } #pathbar .p svg { flex: none; }
  #pathbar .p:hover { background: #26262a; color: var(--fg); }
  #pathbar svg.i { width: 13px; height: 13px; }
  .menu { position: relative; } .caret { font-size: 10px; margin-left: 2px; }
  .menupop { position: absolute; right: 0; top: calc(100% + 6px); z-index: 6; min-width: 230px; background: var(--panel);
             border: 1px solid var(--line); border-radius: 8px; padding: 5px; box-shadow: 0 10px 30px rgba(0,0,0,.5); }
  .mi { display: flex; align-items: center; gap: 9px; width: 100%; background: none; border: 0; color: var(--fg); text-decoration: none;
        padding: 7px 9px; border-radius: 6px; cursor: pointer; font: inherit; text-align: left; flex-wrap: wrap; }
  .mi:hover { background: #26262a; } .mi small { flex-basis: 100%; padding-left: 25px; color: var(--mut); font-size: 11px; }
  #bar .pop { top: 100%; right: 18px; }
  .tab .tl { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
  /* Document tabs: segmented like OpenSelf's, each kind keeps its colour on the icon. */
  #tabs { display: inline-flex; gap: 2px; white-space: nowrap; }
  .tab { display: inline-flex; align-items: center; gap: 7px; background: none; border: 0; color: var(--mut);
         padding: 6px 12px; border-radius: 6px; cursor: pointer; font: inherit; font-size: 13.5px; }
  .tab svg { color: var(--k); } .tab:hover { color: var(--fg); background: var(--hover); }
  .tab.on { color: #fff; background: var(--hover); font-weight: 600; }
  .tab.k-cv { --k: #6aa4f8; } .tab.k-ad { --k: #f0ad4e; } .tab.k-note { --k: #b48cf2; } .tab.k-form { --k: #3fc1a5; }
  .bar { flex-wrap: wrap; }
  .find { display: flex; align-items: center; gap: 6px; background: #101012; border: 1px solid var(--line);
          border-radius: 6px; padding: 0 8px; }
  .find input { background: none; border: 0; color: var(--fg); padding: 5px 0; width: 120px; font: inherit; outline: none; }
  #hits { color: var(--mut); min-width: 48px; font-size: 12px; }
  .pop { position: absolute; top: 100%; right: 14px; z-index: 5; width: 380px; max-height: 60vh; overflow: auto;
         background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 6px;
         box-shadow: 0 10px 30px rgba(0,0,0,.5); }
  .rev { display: flex; flex-direction: column; gap: 1px; width: 100%; text-align: left; background: none; border: 0;
         color: var(--fg); padding: 7px 9px; border-radius: 6px; cursor: pointer; font: inherit; }
  .rev:hover { background: #232328; } .rev.on { background: var(--hl); }
  .rev .top { display: flex; align-items: center; gap: 8px; }
  .rev code { color: var(--acc); font: 12px ui-monospace, Menlo, monospace; }
  .rev .when { color: var(--mut); font-size: 11px; margin-left: auto; }
  .rev .sub { color: var(--mut); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag { display: inline-flex; gap: 4px; align-items: center; font-size: 11px; padding: 0 6px; border-radius: 99px;
         background: #2a2a31; color: var(--fg); }
  .empty { padding: 10px; color: var(--mut); }
  #banner { display: none; align-items: center; gap: 10px; padding: 7px 14px; background: #2d2614;
            border-bottom: 1px solid #4a3d1a; color: #f3d98b; }
  #banner.show { display: flex; }
  #view { overflow: auto; padding: 18px 0 40px; }
  .sheet { position: relative; margin: 0 auto 18px; background: #fff; box-shadow: 0 2px 16px rgba(0,0,0,.55); }
  .sheet canvas { display: block; }
  .textLayer ::selection { background: rgba(60,130,255,.38); }
  .textLayer mark { background: rgba(255,214,10,.55); color: transparent; border-radius: 2px; }
  .textLayer.selecting .endOfContent { top: 0; cursor: text; }
  pre.err { background: #3a1d1d; color: #ffb4ab; margin: 0 auto 16px; max-width: 860px; padding: 12px;
            border-radius: 6px; white-space: pre-wrap; }
  .md mark.hit { background: rgba(255,214,10,.5); color: inherit; border-radius: 2px; }
  .md { max-width: 820px; margin: 0 auto; padding: 4px 24px 48px; font-size: 14px; line-height: 1.65; user-select: text; overflow-wrap: anywhere; }
  .md h1 { font-size: 22px; margin: 28px 0 10px; } .md h2 { font-size: 18px; margin: 26px 0 8px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }
  .md h3 { font-size: 15.5px; margin: 20px 0 6px; } .md h4, .md h5, .md h6 { font-size: 14px; margin: 16px 0 4px; color: var(--mut); }
  .md > :first-child { margin-top: 0; } .md p { margin: 8px 0; } .md ul, .md ol { padding-left: 22px; margin: 8px 0; } .md li { margin: 3px 0; }
  .md li > ul, .md li > ol { margin: 3px 0; } .md a { color: var(--acc); }
  .md code { background: #101012; border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font: 12.5px ui-monospace, Menlo, monospace; }
  .md pre { background: #101012; border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; overflow: auto; }
  .md pre code { background: none; border: 0; padding: 0; }
  .md blockquote { margin: 10px 0; padding: 2px 14px; border-left: 3px solid var(--acc); color: #c9c9d0; background: #1a1a1e; border-radius: 0 6px 6px 0; }
  .md hr { border: 0; border-top: 1px solid var(--line); margin: 28px 0; }
  .md table { border-collapse: collapse; margin: 12px 0; font-size: 13px; display: block; overflow: auto; }
  .md th, .md td { border: 1px solid var(--line); padding: 5px 9px; text-align: left; vertical-align: top; } .md th { background: #1a1a1e; }
  .md strong { color: #fff; }
  .btn.formdl { display: flex; width: fit-content; margin: 0 auto 14px; padding: 6px 14px; color: #3fc1a5; border-color: color-mix(in srgb, #3fc1a5 50%, transparent); }
  #cbox { position: fixed; z-index: 20; width: 310px; background: var(--panel); border: 1px solid var(--acc);
          border-radius: 10px; padding: 10px; box-shadow: 0 12px 34px rgba(0,0,0,.6); display: none; }
  #cbox.show { display: block; }
  #cbox .quote { color: var(--mut); font-style: italic; font-size: 12px; max-height: 3.6em; overflow: hidden;
                 border-left: 2px solid var(--line); padding-left: 8px; margin-bottom: 8px; }
  #cbox textarea { width: 100%; height: 76px; resize: vertical; background: #101012; color: var(--fg);
                   border: 1px solid var(--line); border-radius: 6px; padding: 7px 8px; font: inherit; outline: none; }
  #cbox textarea:focus { border-color: var(--acc); }
  #cbox .row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
  #cbox .hint { color: var(--mut); font-size: 11px; }
  .badge { background: var(--acc); color: #0b1220; border-radius: 99px; font-size: 11px; font-weight: 700; padding: 0 6px; }
  .cm { padding: 8px 9px; border-radius: 6px; display: flex; flex-direction: column; gap: 4px; }
  .cm + .cm { border-top: 1px solid var(--line); }
  .cm .q { color: var(--mut); font-style: italic; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cm .meta { color: var(--mut); font-size: 11px; display: flex; gap: 8px; align-items: center; }
  .cm .act { margin-left: auto; display: flex; gap: 4px; }
  .cm .act button { background: none; border: 1px solid var(--line); color: var(--fg); border-radius: 5px; cursor: pointer; padding: 2px 5px; }
  .cm.done { opacity: .55; }
  .cm .note { color: #9fd3a1; font-size: 12px; }
  .grp .add { margin-left: auto; background: none; border: 1px solid var(--line); color: var(--fg); border-radius: 5px;
              padding: 1px 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; font-size: 11px; text-transform: none; letter-spacing: 0; }
  .grp .add:hover { background: #232328; }
  dialog { background: var(--panel); color: var(--fg); border: 1px solid var(--line); border-radius: 12px; padding: 18px; width: min(640px, 92vw); }
  dialog::backdrop { background: rgba(0,0,0,.55); }
  dialog h2 { margin: 0 0 12px; font-size: 15px; }
  dialog label { display: block; color: var(--mut); font-size: 12px; margin: 10px 0 4px; }
  dialog input, dialog textarea { width: 100%; background: #101012; color: var(--fg); border: 1px solid var(--line);
                                  border-radius: 6px; padding: 8px; font: inherit; outline: none; }
  dialog textarea { height: 280px; resize: vertical; font: 12.5px/1.45 ui-monospace, Menlo, monospace; }
  dialog .row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; align-items: center; }
  dialog .row .msg { margin-right: auto; color: var(--warn); }
  .chip.gen { border-color: var(--acc); color: var(--acc); }
  .tpl { background: #101012; color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; font: inherit; }
  .tplgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .tplcard { display: flex; flex-direction: column; gap: 5px; text-align: left; background: none; border: 0; padding: 0;
             color: var(--fg); cursor: pointer; font: inherit; font-size: 11.5px; min-width: 0; }
  .tplcard .thumb { aspect-ratio: 210 / 297; background: #2a2a31; border-radius: 6px; overflow: hidden; display: block;
                    border: 1px solid var(--line); }
  .tplcard:hover .thumb { border-color: #55555e; } .tplcard.on .thumb { border: 2px solid var(--acc); }
  .tplcard .thumb img { width: 100%; height: 100%; object-fit: cover; object-position: top; display: block; background: #fff; }
  .tplcard b { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tplcard.on b { color: var(--acc); font-weight: 600; }
  /* Narrow window: the rail becomes a panel the Comments button opens. */
  @media (max-width: 1180px) {
    body { grid-template-columns: 220px minmax(0, 1fr) 0; }
    #rail { position: fixed; right: 0; top: 56px; bottom: 0; width: 320px; z-index: 8; display: none; box-shadow: -10px 0 30px rgba(0,0,0,.4); }
    body.rail-open #rail { display: flex; } #cmbtn { display: inline-flex; }
  }
  @media (max-width: 760px) { #nav .nv:not(.on) { display: none; } #side { display: none; } body { grid-template-columns: 0 minmax(0, 1fr) 0; } }
  body.doc .cvonly { display: none !important; }
  .how { max-width: 860px; margin: 0 auto; padding: 4px 24px 40px; line-height: 1.55; }
  .how h1 { font-size: 22px; margin: 6px 0 8px; } .how h2 { font-size: 15px; margin: 26px 0 8px; color: var(--acc); }
  .how .lead { color: var(--mut); font-size: 14px; }
  .how code { background: #101012; border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font-size: 12px; }
  .how table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  .how th, .how td { text-align: left; vertical-align: top; padding: 7px 9px; border-bottom: 1px solid var(--line); }
  .how th { color: var(--mut); font-weight: 600; }
  .how li { margin: 4px 0; }
  .flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px; margin: 10px 0; }
  .flow .box { flex: 1 1 170px; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: #1a1a1e; display: flex; flex-direction: column; gap: 3px; }
  .flow .box span { color: var(--mut); font-size: 12px; }
  .flow .shared { border-color: #4a6fa5; } .flow .mine { border-color: #5a8a5e; } .flow .case { border-color: #a58a4a; }
  .flow .gen { border-color: var(--acc); background: #1b2433; } .flow .you { border-color: #a5694a; }
  .flow .plus { align-self: center; color: var(--mut); font-size: 18px; }
  .flow .arrow { flex-basis: 100%; text-align: center; color: var(--mut); font-size: 18px; line-height: 1; }
  .flow .arrow.loop { font-size: 12px; font-style: italic; }
  #toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); background: #2b2b31;
           border: 1px solid var(--line); padding: 8px 14px; border-radius: 8px; opacity: 0; transition: opacity .2s;
           pointer-events: none; }
  #toast.show { opacity: 1; }
</style></head><body>
__ICONS__
<header id="top">
  <div class="brand"><span class="logo">OV</span>OpenVita</div>
  <nav id="nav" aria-label="Views"></nav>
  <span class="sp"></span>
  <label class="find"><svg class="i"><use href="#i-search"/></svg><input id="q" type="search" data-tp="search"><span id="hits"></span></label>
  <button id="who" aria-haspopup="true"><span class="av" id="whoav"></span><span id="whoname"></span><span class="caret">▾</span></button>
  <div class="menupop" id="people" hidden></div>
</header>
<aside id="side"></aside>
<main id="main">
  <div id="bar">
    <span id="tabs" class="cvonly"></span>
    <div class="state"><span class="dot" id="dot"></span><span id="msg" data-t="loading"></span>
      <span class="chip gen cvonly" id="genchip" data-t="genQueued" hidden></span></div>
    <div id="pathbar"></div>
    <span class="sp"></span>
    <button class="btn cvonly" id="draftbtn" data-tt="draftTip"><svg class="i"><use href="#i-data"/></svg><span class="lbl" data-t="draft"></span></button>
    <button class="btn cvonly" id="revbtn" data-tt="revisionsTip"><svg class="i"><use href="#i-clock"/></svg><span class="lbl" data-t="revisions"></span></button>
    <button class="btn cvonly" id="savebtn" data-tt="saveTip"><svg class="i"><use href="#i-save"/></svg><span class="lbl" data-t="saveRev"></span><span class="pip" id="dirty" data-tt="unsaved" hidden></span></button>
    <button class="btn second cvonly" id="genbtn" data-tt="genTip" hidden><svg class="i"><use href="#i-spark"/></svg><span class="lbl" data-t="generate"></span></button>
    <button class="btn" id="cmbtn" data-tt="commentsTip"><svg class="i"><use href="#i-chat"/></svg><span class="badge" id="cmcount2" hidden></span></button>
    <div class="menu cvonly"><button class="btn primary" id="pdfbtn" data-tt="pdfTip"><svg class="i"><use href="#i-file"/></svg><span data-t="exportPdf"></span><span class="caret">▾</span></button>
      <div class="menupop" id="pdfmenu" hidden>
        <a class="mi" id="pdflink" href="#" target="_blank" draggable="true" data-tt="dragTip"><svg class="i"><use href="#i-open"/></svg><span data-t="openTab"></span></a>
        <a class="mi" id="pdfdl" href="#" download><svg class="i"><use href="#i-save"/></svg><span data-t="download"></span></a>
        <button class="mi mac" id="copybtn"><svg class="i"><use href="#i-copy"/></svg><span data-t="copyFile"></span><small data-t="copyHint"></small></button>
        <button class="mi mac" id="finderbtn"><svg class="i"><use href="#i-folder"/></svg><span data-t="finder"></span></button>
      </div></div>
    <div class="pop" id="pop" hidden></div>
  </div>
  <div id="banner"><svg class="i"><use href="#i-clock"/></svg><span id="bannertext"></span><span class="sp"></span>
    <button class="btn" id="backbtn"><svg class="i"><use href="#i-back"/></svg><span data-t="backToCurrent"></span></button></div>
  <div id="view"></div>
</main>
<aside id="rail">
  <p class="rh"><span data-t="comments"></span><span class="badge" id="cmcount" hidden></span></p>
  <div id="cmlist"></div>
  <div id="tplsec" class="cvonly">
    <p class="rh" data-tt="templateLead"><span data-t="template"></span><small id="tpllabel"></small></p>
    <div class="tplgrid" id="tplgrid"></div>
  </div>
</aside>
<div id="cbox"><div class="quote" id="cquote"></div>
  <textarea id="ctext" data-tp="commentPh"></textarea>
  <div class="row"><button class="btn on" id="csend"><svg class="i"><use href="#i-chat"/></svg><span data-t="send"></span></button>
  <button class="btn" id="ccancel" data-t="cancel"></button><span class="hint" data-t="sendHint"></span></div></div>
<dialog id="newcase"><h2 data-t="newApp"></h2>
  <label for="ncname" data-t="folderName"></label><input id="ncname" autocomplete="off" placeholder="2026-10-acme-platform-engineer">
  <label for="nctpl" data-t="templateLabel"></label><select class="tpl" id="nctpl"></select>
  <label for="ncad" data-t="adLabel"></label><textarea id="ncad" data-tp="adPh"></textarea>
  <div class="row"><span class="msg" id="ncmsg"></span><button class="btn" id="nccancel" data-t="cancel"></button>
  <button class="btn on" id="nccreate"><svg class="i"><use href="#i-plus"/></svg><span data-t="create"></span></button></div></dialog>
<div id="toast"></div>
<script src="/vendor/pdfjs/pdf.min.js"></script>
<script src="/vendor/marked/marked.min.js"></script>
<script src="/openself/app.js"></script>
<script src="/static/profile.js"></script>
<script>
pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.js';
const $ = id => document.getElementById(id);
// UI strings. The language follows the person whose files are open (tree[].lang from the server).
const T = {
  en: { loading: 'Loading ...', genQueued: 'Tailoring requested', search: 'Search the text', comments: 'Comments',
    commentsTip: 'Comments for the assistant', revisions: 'Revisions', revisionsTip: 'Earlier saved versions', save: 'Save',
    saveTip: 'Save a new revision', unsaved: 'Unsaved changes', generate: 'Tailor CV',
    genTip: 'Ask the assistant to tailor the CV from the job ad, the profile and the instructions',
    draft: 'Draft from profile', draftTip: 'Rebuild this CV straight from the profile. Only replaces a CV nobody edited since the last draft, unless you confirm.',
    templateTip: 'Template: how the CV looks. The content is the same in every template.', template: 'Template', pdfTip: 'Share or open the PDF',
    dragTip: 'Drag to Slack or email (Chrome)', openTab: 'Open in a new tab', copyFile: 'Copy the file', copyHint: 'paste into Slack or email',
    finder: 'Show in Finder', backToCurrent: 'Back to current', commentPh: 'What should change? The assistant sees this.', send: 'Send',
    cancel: 'Cancel', sendHint: 'Cmd+Enter sends', newApp: 'New application', folderName: 'Folder name (yyyy-mm-company-role)',
    templateLabel: 'Template (how the CV looks, the content is the same)', adLabel: 'The job ad. Paste all of it, including any email from a broker.',
    adPh: 'Paste the job ad here', create: 'Create', copyPath: 'Click to copy the full path', pathCopied: 'Path copied',
    readOnly: 'Read only. Select text to comment.', shared: 'Shared', howItWorks: 'How it works', instructions: 'Instructions',
    profile: 'Profile', profileNone: 'no profile', personal: 'Personal instructions', baseCvs: 'Base CVs', apps: 'Applications',
    newBtn: 'New', newAppTip: 'New application from a job ad', generic: 'General', adTab: 'Job ad', notesTab: 'Notes', formTab: 'Form: ',
    showingRev: 'Showing revision {0}, {1}. {2}', hits: '{0} hits', couldNotFetch: 'Could not fetch', notFound: 'Not found: {0}',
    revision: 'Revision', building: 'Building ...', buildError: 'Build error', updated: 'Updated {0}', lostServer: 'Lost contact with the server',
    buildingForm: 'Building form ...', formError: 'Could not make the form:\n', downloadDocx: 'Download filled .docx', updatedPlain: 'Updated',
    noPdf: 'PDF not found. Wait until it is built.', today: 'today', yesterday: 'yesterday', daysAgo: '{0} days ago', fetching: 'Fetching ...',
    current: 'Current', unsavedChanges: 'unsaved changes', saved: 'saved', noRevs: 'No saved revisions of this CV yet.', buildingRev: 'Building revision ...',
    describeRev: 'Describe the revision (saves all of {0}\'s folder)', savedPlain: 'Saved', notSaved: 'Could not save',
    nameFormat: 'The name must be yyyy-mm-company-role', pasteAd: 'Paste the job ad first', notCreated: 'Could not create',
    appCreated: 'Application created. Press Tailor CV when the job ad looks right.', requested: 'Requested', notRequested: 'Could not request',
    source: 'Source', switched: 'Template switched', notSwitched: 'Could not switch template', templateFor: 'Template for this CV',
    templateLead: 'The template is the look: layout, colours and fonts. The content of the CV stays the same in every template. You can switch back and forth, the previous version is saved as a revision.',
    inUse: 'In use', default: ' (default)', sentToAssistant: 'Sent to the assistant', notStored: 'Could not store the comment',
    noComments: 'No comments yet. Select text in the CV, the job ad or the profile and write what should change.',
    genItem: 'Tailor the CV to the job ad', interview: 'Interview about {0}', theProfile: 'the profile', page: ' p.', assistant: 'Assistant: ',
    markDone: 'Mark as done', reopen: 'Open again', archive: 'Hide from the list (kept for later tuning)', shownFinder: 'Shown in Finder',
    pdfCopied: 'PDF copied, paste with Cmd+V', noProfileYet: 'No profile connected yet. Run `make connect C={0} PROFILE=<path>` to use an existing OpenSelf profile, or `make profile-init C={0}` to start one.',
    editedSinceDraft: 'This CV was edited after its last draft. Replace it with a new draft from the profile? The current version is saved as a revision first.',
    drafting: 'Drafting from the profile ...', saveRev: 'Save revision', exportPdf: 'Export PDF', download: 'Download',
    cvs: 'CVs', people: 'People', health: 'Profile', healthCounts: '{0} assignments · {1} employments', healthQs: '{0} open questions',
    healthNone: 'No profile connected yet', forAssistant: 'For the assistant', empty: 'No people yet. Run `make new-person C=<name>` (see README.md).' },
  nb: { loading: 'Laster ...', genQueued: 'Skreddersøm bestilt', search: 'Søk i teksten', comments: 'Kommentarer',
    commentsTip: 'Kommentarer til assistenten', revisions: 'Revisjoner', revisionsTip: 'Tidligere lagrede versjoner', save: 'Lagre',
    saveTip: 'Lagre ny revisjon', unsaved: 'Ulagrede endringer', generate: 'Skreddersy CV',
    genTip: 'Be assistenten skreddersy CV-en ut fra annonsen, profilen og instruksjonene',
    draft: 'Lag fra profilen', draftTip: 'Lag CV-en på nytt rett fra profilen. Erstatter bare en CV ingen har endret siden forrige utkast, med mindre du bekrefter.',
    templateTip: 'Mal: utseendet til CV-en. Innholdet er det samme i alle maler.', template: 'Mal', pdfTip: 'Del eller åpne PDF-en',
    dragTip: 'Dra til Slack eller e-post (Chrome)', openTab: 'Åpne i ny fane', copyFile: 'Kopier filen', copyHint: 'lim inn i Slack eller e-post',
    finder: 'Vis i Finder', backToCurrent: 'Tilbake til gjeldende', commentPh: 'Hva vil du ha endret? Assistenten ser dette.', send: 'Send',
    cancel: 'Avbryt', sendHint: 'Cmd+Enter sender', newApp: 'Ny søknad', folderName: 'Mappenavn (yyyy-mm-firma-rolle)',
    templateLabel: 'Mal (utseendet til CV-en, innholdet er det samme)', adLabel: 'Annonsen. Lim inn hele teksten, også e-post fra en megler.',
    adPh: 'Lim inn annonsen her', create: 'Opprett', copyPath: 'Klikk for å kopiere hele stien', pathCopied: 'Sti kopiert',
    readOnly: 'Skrivebeskyttet. Marker tekst for å kommentere.', shared: 'Delt', howItWorks: 'Slik virker det', instructions: 'Instruksjoner',
    profile: 'Profil', profileNone: 'ingen profil', personal: 'Personlige instruksjoner', baseCvs: 'Generelle CV-er', apps: 'Søknader',
    newBtn: 'Ny', newAppTip: 'Ny søknad fra en annonse', generic: 'Generell', adTab: 'Annonse', notesTab: 'Notater', formTab: 'Skjema: ',
    showingRev: 'Viser revisjon {0}, {1}. {2}', hits: '{0} treff', couldNotFetch: 'Kunne ikke hente', notFound: 'Fant ikke {0}',
    revision: 'Revisjon', building: 'Bygger ...', buildError: 'Byggefeil', updated: 'Oppdatert {0}', lostServer: 'Mistet kontakt med serveren',
    buildingForm: 'Bygger skjema ...', formError: 'Kunne ikke lage skjemaet:\n', downloadDocx: 'Last ned utfylt .docx', updatedPlain: 'Oppdatert',
    noPdf: 'Fant ikke PDF-filen. Vent til den er bygget.', today: 'i dag', yesterday: 'i går', daysAgo: '{0} dager siden', fetching: 'Henter ...',
    current: 'Gjeldende', unsavedChanges: 'ulagrede endringer', saved: 'lagret', noRevs: 'Ingen lagrede revisjoner av denne CV-en ennå.', buildingRev: 'Bygger revisjon ...',
    describeRev: 'Beskriv revisjonen (lagrer hele mappen til {0})', savedPlain: 'Lagret', notSaved: 'Kunne ikke lagre',
    nameFormat: 'Navnet må være yyyy-mm-firma-rolle', pasteAd: 'Lim inn annonsen først', notCreated: 'Kunne ikke opprette',
    appCreated: 'Søknad opprettet. Trykk Skreddersy CV når annonsen ser riktig ut.', requested: 'Bestilt', notRequested: 'Kunne ikke bestille',
    source: 'Kilde', switched: 'Mal byttet', notSwitched: 'Kunne ikke bytte mal', templateFor: 'Mal for denne CV-en',
    templateLead: 'Malen er utseendet: layout, farger og skrifter. Innholdet i CV-en er det samme, uansett mal. Du kan bytte frem og tilbake, forrige versjon lagres som en revisjon.',
    inUse: 'Bruker nå', default: ' (standard)', sentToAssistant: 'Sendt til assistenten', notStored: 'Kunne ikke lagre kommentaren',
    noComments: 'Ingen kommentarer ennå. Marker tekst i CV-en, annonsen eller profilen og skriv hva som skal endres.',
    genItem: 'Skreddersy CV-en til annonsen', interview: 'Intervju om {0}', theProfile: 'profilen', page: ' s.', assistant: 'Assistenten: ',
    markDone: 'Merk som gjort', reopen: 'Åpne igjen', archive: 'Skjul fra lista (lagres fortsatt for senere tuning)', shownFinder: 'Vist i Finder',
    pdfCopied: 'PDF kopiert, lim inn med Cmd+V', noProfileYet: 'Ingen profil koblet til ennå. Kjør `make connect C={0} PROFILE=<sti>` for å bruke en OpenSelf-profil du har, eller `make profile-init C={0}` for å starte en.',
    editedSinceDraft: 'Denne CV-en er endret etter forrige utkast. Erstatte den med et nytt utkast fra profilen? Gjeldende versjon lagres som revisjon først.',
    drafting: 'Lager fra profilen ...', saveRev: 'Lagre revisjon', exportPdf: 'Eksporter PDF', download: 'Last ned',
    cvs: 'CV-er', people: 'Personer', health: 'Profil', healthCounts: '{0} oppdrag · {1} ansettelser', healthQs: '{0} åpne spørsmål',
    healthNone: 'Ingen profil koblet til ennå', forAssistant: 'For assistenten', empty: 'Ingen personer ennå. Kjør `make new-person C=<navn>` (se README.md).' },
};
let LANG = 'en';
const tr = (k, ...a) => { let s = (T[LANG] || T.en)[k] ?? T.en[k] ?? k; a.forEach((v, i) => { s = s.split('{' + i + '}').join(v); }); return s; };
const LOCALE = () => LANG === 'nb' ? 'nb-NO' : undefined;
function applyLang() {
  const p = tree.find(x => x.person === ctxC); LANG = (p && p.lang) || (tree[0] && tree[0].lang) || 'en';
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-t]').forEach(n => { n.textContent = tr(n.dataset.t); });
  document.querySelectorAll('[data-tp]').forEach(n => { n.placeholder = tr(n.dataset.tp); });
  document.querySelectorAll('[data-tt]').forEach(n => { n.title = tr(n.dataset.tt); });
  document.querySelectorAll('.mac').forEach(n => { n.hidden = !/Mac/.test(navigator.platform); });
}
const START = __START__;
let target = decodeURIComponent(location.hash.slice(1)) || START || (() => { try { return localStorage.getItem('openvita.target'); } catch (e) { return ''; } })() || '';
const isDoc = t => /^doc\/(how|prompt)$/.test(t) || /^[\w.-]+\/(raw|personal)$/.test(t);
let ctxC = '';  // the person whose files comments are stored with, also while a shared doc is open
const consC = () => target.startsWith('doc/') ? ctxC : target.split('/')[0];
let formShown = '';
let tab = 'cv', version = -1, rendering = false, tree = [], files = [], rev = null, revs = null;
let pointerDown = false, prevRange = null;  // text selection state, see "Text selection in the PDF"

const icon = n => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('class', 'i');
  const u = document.createElementNS('http://www.w3.org/2000/svg', 'use'); u.setAttribute('href', '#i-' + n); s.append(u); return s; };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const toast = t => { const e = $('toast'); e.textContent = t; e.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove('show'), 2600); };
const q = (o) => new URLSearchParams(o).toString();

function drawTitle() {
  const on = document.querySelector('#side .item.on span, #nav .nv.on span');
  document.title = (on ? on.textContent + ' · ' : '') + 'OpenVita';
}
// The CV last open per person, so "CVs" in the header goes back to it.
const lastCv = c => { try { return localStorage.getItem('openvita.cv.' + c) || ''; } catch (e) { return ''; } };
function cvOf(c) {
  const p = tree.find(x => x.person === c); if (!p) return 'doc/how';
  const last = lastCv(c), ok = last && (p.base.some(v => last === c + '/base/' + v) || p.apps.some(a => last === c + '/applications/' + a));
  return ok ? last : p.base.length ? c + '/base/' + p.base[0] : p.apps.length ? c + '/applications/' + p.apps[0] : c + '/raw';
}
function drawNav() {
  const nav = $('nav'), c = ctxC, p = tree.find(x => x.person === c); nav.replaceChildren();
  const kind = target.startsWith('doc/how') ? 'how' : target.startsWith('doc/prompt') ? 'prompt' : target.endsWith('/raw') ? 'raw'
    : target.endsWith('/personal') ? 'personal' : 'cv';
  const mk = (k, label, to, badge) => { const b = el('button', 'nv' + (k === kind ? ' on' : '')); b.append(el('span', '', label));
    if (badge) b.append(el('span', 'badge', badge)); b.onclick = () => setTarget(to); nav.append(b); };
  if (p) { mk('cv', tr('cvs'), cvOf(c)); mk('raw', tr('profile'), c + '/raw', p.stats && p.stats.questions ? String(p.stats.questions) : ''); }
  mk('prompt', tr('instructions'), 'doc/prompt'); mk('how', tr('howItWorks'), 'doc/how');
  $('whoname').textContent = c || '—'; $('whoav').textContent = (c || '?').slice(0, 2);
  const menu = $('people'); menu.replaceChildren(el('div', 'empty', tr('people')));
  for (const x of tree) { const b = el('button', 'mi'); b.append(icon('user'), el('span', '', x.person));
    b.onclick = () => { menu.hidden = true; ctxC = x.person; setTarget(cvOf(x.person)); }; menu.append(b); }
}
function setTarget(t) {
  target = t; tab = 'cv'; version = -1; rev = null; revs = null; $('pop').hidden = true; $('view').classList.remove('pfmode');
  $('pathbar').replaceChildren(); $('pathbar').dataset.sig = '';
  if (!t.startsWith('doc/')) ctxC = t.split('/')[0];
  applyLang();
  document.body.classList.toggle('doc', isDoc(t));
  location.hash = encodeURIComponent(t); try { localStorage.setItem('openvita.target', t); } catch (e) { /* private window */ }
  if (/\/(base|applications)\//.test(t)) { try { localStorage.setItem('openvita.cv.' + ctxC, t); } catch (e) { /* private window */ } }
  document.body.classList.remove('rail-open');
  drawSide(); drawNav(); drawBanner(); $('view').scrollTop = 0; tick(true); loadComments(); drawTitle();
  $('genbtn').hidden = !t.includes('/applications/');
}
// Markdown to safe HTML: marked, then a small sanitizer (pasted job ads can contain anything).
function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script,style,iframe,object,embed,link,meta,form,input,button,textarea,select,svg,math').forEach(n => n.remove());
  doc.querySelectorAll('img').forEach(n => n.replaceWith(doc.createTextNode(n.alt || '')));
  doc.querySelectorAll('*').forEach(n => {
    for (const a of [...n.attributes]) {
      const nm = a.name.toLowerCase(), v = a.value.trim().toLowerCase();
      if (nm.startsWith('on') || nm === 'style' || (nm === 'href' && /^(javascript|data|vbscript):/.test(v))) n.removeAttribute(a.name);
    }
    if (n.tagName === 'A') { n.target = '_blank'; n.rel = 'noopener noreferrer'; }
  });
  return doc.body.innerHTML;
}
function renderMd(text, breaks) {
  const box = el('div', 'md'); box.innerHTML = sanitize(marked.parse(text, { gfm: true, breaks: !!breaks })); return box;
}
function drawPath(paths, root) {
  const bar = $('pathbar'), sig = JSON.stringify([paths, root]);
  if (bar.dataset.sig === sig) return; bar.dataset.sig = sig; bar.replaceChildren();
  for (const [label, rel] of paths) {
    const b = el('button', 'p'); b.title = rel + '\n' + tr('copyPath'); b.append(icon('file'), el('span', '', (label ? label + ': ' : '') + rel.split('/').pop())); b.onclick = async () => { try { await navigator.clipboard.writeText(root + '/' + rel); toast(tr('pathCopied')); } catch (e) { toast(root + '/' + rel); } };
    bar.append(b);
  }
}
async function showDoc() {
  const d = await (await fetch('/doc?' + q({ t: target }), { cache: 'no-store' })).json(), view = $('view');
  $('dot').className = 'dot'; $('msg').textContent = tr('readOnly');
  drawPath((d.files || []).map(f => ['', f]), d.root);
  if (target.endsWith('/raw')) { view.replaceChildren(renderMd(tr('noProfileYet', target.split('/')[0]), false)); return; }
  if (d.type === 'html') { const box = el('div'); box.innerHTML = d.body; view.replaceChildren(box); $('hits').textContent = ''; }
  else { view.replaceChildren(renderMd(d.body, false)); highlight(); }
}
function drawSide() {
  const side = $('side'); side.replaceChildren();
  const add = (icn, label, small, k, two) => { const b = el('button', 'item' + (two ? ' two' : '') + (k === target ? ' on' : ''));
    if (!two) b.append(icon(icn)); b.append(el('span', '', label));
    if (small) b.append(el('small', '', small)); b.onclick = () => setTarget(k); side.append(b); };
  const grp = (text, onAdd) => { const g = el('div', 'grp'); g.append(el('span', '', text));
    if (onAdd) { const b = el('button', 'add'); b.append(icon('plus'), tr('newBtn')); b.title = tr('newAppTip'); b.onclick = onAdd; g.append(b); } side.append(g); };
  const c = tree.find(x => x.person === ctxC);
  if (!c) { side.append(el('div', 'empty', tr('empty'))); return; }
  if (c.base.length) { grp(tr('baseCvs'));
    for (const v of c.base) add('file', v === 'generic' ? tr('generic') : v, '', c.person + '/base/' + v); }
  grp(tr('apps'), () => openNewCase(c.person));
  for (const a of c.apps) add('', a.replace(/^\d{4}-\d{2}-/, '').replace(/-/g, ' '), a.slice(0, 7), c.person + '/applications/' + a, true);
  grp(tr('forAssistant')); add('spark', tr('personal'), 'tuning', c.person + '/personal');
  const h = el('button', 'health'); h.append(el('b', '', tr('health')));
  if (c.stats) { h.append(el('span', '', tr('healthCounts', c.stats.assignments, c.stats.employments)));
    if (c.stats.questions) h.append(el('span', 'q', tr('healthQs', c.stats.questions))); }
  else h.append(el('span', '', tr('healthNone')));
  h.onclick = () => setTarget(c.person + '/raw'); side.append(h);
}
function drawTabs() {
  const tabs = $('tabs'); tabs.replaceChildren();
  const mk = (id, icn, label, kind) => { const b = el('button', 'tab k-' + kind + (tab === id ? ' on' : '')); b.append(icon(icn), el('span', 'tl', label));
    b.title = label; b.onclick = () => { tab = id; version = -1; drawTabs(); tick(true); }; tabs.append(b); };
  mk('cv', 'file', 'CV', 'cv'); if (files.includes('job-ad.md')) mk('job-ad.md', 'ad', tr('adTab'), 'ad'); if (files.includes('notes.md')) mk('notes.md', 'note', tr('notesTab'), 'note');
  for (const f of files) if (f.startsWith('form:')) mk(f, 'tag', tr('formTab') + f.slice(5), 'form');
}
function drawBanner() {
  const b = $('banner');
  if (!rev) { b.classList.remove('show'); return; }
  $('bannertext').textContent = tr('showingRev', rev.hash, new Date(rev.time * 1000).toLocaleString(LOCALE()), rev.subject);
  b.classList.add('show');
}
async function renderPdf(url) {
  const pdf = await pdfjsLib.getDocument(url).promise;
  // At least 2x: Firefox with fingerprinting protection reports 1 on a retina screen, which blurs the pages.
  const view = $('view'), dpr = Math.max(2, window.devicePixelRatio || 1);
  const width = Math.min(view.clientWidth - 40, 900), frag = document.createDocumentFragment();
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i), v1 = page.getViewport({ scale: 1 });
    const scale = width / v1.width, vp = page.getViewport({ scale });
    const sheet = el('div', 'sheet'); sheet.style.cssText = `width:${vp.width}px;height:${vp.height}px;--scale-factor:${scale}`;
    const cv = el('canvas'); cv.width = vp.width * dpr; cv.height = vp.height * dpr; cv.style.cssText = `width:${vp.width}px;height:${vp.height}px`;
    const tl = el('div', 'textLayer'); sheet.append(cv, tl); frag.append(sheet);
    await page.render({ canvasContext: cv.getContext('2d'), viewport: vp, transform: [dpr, 0, 0, dpr, 0, 0] }).promise;
    const tc = await page.getTextContent();
    await pdfjsLib.renderTextLayer({ textContent: tc, textContentSource: tc, container: tl, viewport: vp, textDivs: [] }).promise;
    tl.append(el('div', 'endOfContent'));
  }
  return frag;
}
function highlightDom(root, needle, jump) {
  for (const m of root.querySelectorAll('mark.hit')) m.replaceWith(document.createTextNode(m.textContent));
  root.normalize(); let n = 0, first = null;
  if (needle) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const tn of nodes) {
      const t = tn.nodeValue, low = t.toLowerCase(); if (!low.includes(needle)) continue;
      const frag = document.createDocumentFragment(); let at = 0, i;
      while ((i = low.indexOf(needle, at)) >= 0) { frag.append(t.slice(at, i)); const m = el('mark', 'hit', t.slice(i, i + needle.length)); frag.append(m); first = first || m; at = i + needle.length; n++; }
      frag.append(t.slice(at)); tn.replaceWith(frag);
    }
  }
  $('hits').textContent = needle ? tr('hits', n) : '';
  if (first && jump) first.scrollIntoView({ block: 'center' });
}
function highlight(jump) {
  const needle = $('q').value.trim().toLowerCase(); let n = 0;
  if (pfActive()) { pfSearch(needle, jump); return; }
  const md = document.querySelector('.md'); if (md) { highlightDom(md, needle, jump); return; }
  for (const m of document.querySelectorAll('.textLayer mark')) m.replaceWith(m.textContent);
  document.querySelectorAll('.textLayer span').forEach(s => s.normalize());
  if (needle) for (const s of document.querySelectorAll('.textLayer span')) {
    const t = s.textContent, low = t.toLowerCase(); if (!low.includes(needle) || s.children.length) continue;
    const frag = document.createDocumentFragment(); let at = 0, i;
    while ((i = low.indexOf(needle, at)) >= 0) { frag.append(t.slice(at, i)); const m = el('mark', '', t.slice(i, i + needle.length)); frag.append(m); at = i + needle.length; n++; }
    frag.append(t.slice(at)); s.replaceChildren(frag);
  }
  $('hits').textContent = needle ? tr('hits', n) : '';
}
async function show(url, err) {
  rendering = true;
  try {
    const frag = err ? null : await renderPdf(url);
    const view = $('view'), y = view.scrollTop, out = [];
    if (err) out.push(el('pre', 'err', err));
    if (frag) out.push(frag);
    if (err && view.querySelector('.sheet')) { view.querySelector('pre.err')?.remove(); view.prepend(out[0]); }
    else view.replaceChildren(...out);
    view.scrollTop = y; highlight();
  } finally { rendering = false; }
}
async function tick(force) {
  if (!target) { setTimeout(tick, 800); return; }
  if (isDoc(target)) {
    document.body.classList.add('doc');
    if (pfActive()) { await profileTick(); setTimeout(tick, 1500); return; }
    if (version !== -4) { version = -4; try { await showDoc(); } catch (e) { $('msg').textContent = tr('couldNotFetch'); } }
    setTimeout(tick, 1500); return;
  }
  document.body.classList.remove('doc');
  try {
    const s = await (await fetch('/state?' + q({ t: target }), { cache: 'no-store' })).json();
    if (JSON.stringify(tree) !== JSON.stringify(s.tree)) { tree = s.tree; applyLang(); drawSide(); drawNav(); drawTitle(); }
    if (!s.ok) { $('msg').textContent = tr('notFound', target); setTimeout(tick, 1500); return; }
    $('dot').className = 'dot' + (s.building ? ' busy' : s.error ? ' err' : '');
    $('msg').textContent = rev ? tr('revision') : s.building ? tr('building') : s.error ? tr('buildError') : tr('updated', s.built);
    $('dirty').hidden = !s.dirty || !!rev;
    fillTemplates(s.templates || [], s.template || '');
    $('pdflink').href = pdfUrl(); $('pdfdl').href = pdfUrl(); $('pdfdl').download = pdfName(); lastState = s; drawPaths();
    if (JSON.stringify(files) !== JSON.stringify(s.files) || force === true) { files = s.files; drawTabs(); }
    const view = $('view');
    if (tab !== 'cv') {
      if (tab.startsWith('form:')) {
        // Rendered again when the form or its answers change, so the assistant's edits show up while it is open.
        const name = tab.slice(5), fv = s.formver[name] + ':' + name;
        if ((version !== -2 || fv !== formShown) && !rendering && !pointerDown && !$('cbox').classList.contains('show')) {
          version = -2; formShown = fv; $('msg').textContent = tr('buildingForm'); $('dot').className = 'dot busy';
          const r = await fetch('/form-pdf?' + q({ t: target, name, v: fv }), { cache: 'no-store' });
          if (r.ok) await show(URL.createObjectURL(await r.blob()), ''); else await show('', tr('formError') + await r.text());
          const a = el('a', 'btn formdl'); a.href = '/form-docx?' + q({ t: target, name }); a.download = name + '.docx';
          a.append(icon('open'), tr('downloadDocx')); view.prepend(a);
          $('msg').textContent = r.ok ? tr('updatedPlain') : tr('buildError'); $('dot').className = 'dot' + (r.ok ? '' : ' err'); }
      } else if (version !== -2) { version = -2; formShown = '';
        const txt = await (await fetch('/file?' + q({ t: target, name: tab }), { cache: 'no-store' })).text();
        view.replaceChildren(renderMd(txt, tab === 'job-ad.md')); highlight(); }
    } else if (rev) {
      if (version !== -3 && !rendering) { version = -3; await show('/rev-pdf?' + q({ t: target, r: rev.hash }), ''); }
    } else if (!s.building && s.version > 0 && s.version !== version && !rendering
               && !pointerDown && !$('cbox').classList.contains('show')) {  // a new PDF would drop the selection
      const seen = s.version; await show('/pdf?' + q({ t: target, v: s.version }), s.error); version = seen;
    }
  } catch (e) { $('dot').className = 'dot err'; $('msg').textContent = tr('lostServer'); }
  setTimeout(tick, 300);
}
const pdfUrl = () => rev ? '/rev-pdf?' + q({ t: target, r: rev.hash }) : '/pdf?' + q({ t: target });
const pdfName = () => target.split('/').pop() + (rev ? '-' + rev.hash : '') + '.pdf';
// Chrome and Edge let a link be dragged out of the page as a file (Slack, Mail, Finder).
$('pdflink').addEventListener('dragstart', e => e.dataTransfer.setData('DownloadURL', 'application/pdf:' + pdfName() + ':' + location.origin + pdfUrl()));
async function fileAction(path, done) {
  const r = await fetch(path, { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ t: target, r: rev ? rev.hash : '' }) });
  const j = await r.json(); toast(j.ok ? done : (j.message || tr('noPdf')));
}
const rel = t => { const d = (Date.now() / 1000 - t) / 86400; return d < 1 ? tr('today') : d < 2 ? tr('yesterday') : tr('daysAgo', Math.floor(d)); };
async function openRevs() {
  const pop = $('pop'); if (!pop.hidden) { pop.hidden = true; return; }
  pop.hidden = false; pop.replaceChildren(el('div', 'empty', tr('fetching')));
  revs = await (await fetch('/revisions?' + q({ t: target }), { cache: 'no-store' })).json();
  pop.replaceChildren();
  const cur = el('button', 'rev' + (!rev ? ' on' : '')); const top = el('div', 'top');
  top.append(icon('file'), el('b', '', tr('current')), el('span', 'when', revs.dirty ? tr('unsavedChanges') : tr('saved')));
  cur.append(top); cur.onclick = () => { rev = null; version = -1; pop.hidden = true; drawBanner(); tick(true); }; pop.append(cur);
  if (!revs.items.length) pop.append(el('div', 'empty', tr('noRevs')));
  for (const r of revs.items) {
    const b = el('button', 'rev' + (rev && rev.hash === r.hash ? ' on' : '')), t = el('div', 'top');
    t.append(icon('clock'), el('code', '', r.hash));
    for (const tg of r.tags) { const g = el('span', 'tag'); g.append(icon('tag'), tg); t.append(g); }
    t.append(el('span', 'when', rel(r.time) + ', ' + new Date(r.time * 1000).toLocaleDateString(LOCALE())));
    b.append(t, el('div', 'sub', r.subject));
    b.onclick = () => { rev = r; version = -1; pop.hidden = true; drawBanner(); $('msg').textContent = tr('buildingRev'); tick(true); };
    pop.append(b);
  }
}
async function saveRev() {
  const c = target.split('/')[0];
  const msg = prompt(tr('describeRev', c), '');
  if (msg === null) return;
  const r = await fetch('/save', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ c, message: msg.trim() }) });
  const j = await r.json(); toast(j.message || (j.ok ? tr('savedPlain') : tr('notSaved'))); revs = null; tick(true);
}
let ncPerson = '';
function openNewCase(c) {
  ncPerson = c; $('ncname').value = new Date().toISOString().slice(0, 7) + '-'; $('ncad').value = ''; $('ncmsg').textContent = '';
  $('newcase').showModal(); $('ncname').focus();
}
async function createCase() {
  const name = $('ncname').value.trim(), jobad = $('ncad').value.trim();
  if (!/^\d{4}-\d{2}-[\w.-]+$/.test(name)) { $('ncmsg').textContent = tr('nameFormat'); return; }
  if (jobad.length < 40) { $('ncmsg').textContent = tr('pasteAd'); return; }
  $('nccreate').disabled = true;
  const r = await fetch('/new-case', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ c: ncPerson, name, jobad, template: $('nctpl').value }) });
  const j = await r.json(); $('nccreate').disabled = false;
  if (!j.ok) { $('ncmsg').textContent = j.message || tr('notCreated'); return; }
  $('newcase').close(); const s = await (await fetch('/state', { cache: 'no-store' })).json(); tree = s.tree;
  setTarget(j.target); tab = 'job-ad.md'; toast(tr('appCreated'));
}
async function generate() {
  const r = await fetch('/generate', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ t: target }) });
  const j = await r.json(); toast(j.message || (j.ok ? tr('requested') : tr('notRequested'))); loadComments();
}
async function redraft() {
  const post = force => fetch('/draft', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ t: target, force }) }).then(r => r.json());
  $('msg').textContent = tr('drafting');
  let j = await post(false);
  if (j.edited) { if (!confirm(tr('editedSinceDraft'))) { tick(true); return; } j = await post(true); }
  if (j.message) toast(j.message);
  revs = null; version = -1; tick(true);
}
let lastState = null;
function drawPaths() {
  const s = lastState; if (!s || isDoc(target)) return;
  const key = tab === 'cv' ? 'cv' : tab, main = (s.paths[key] || s.paths.cv).map(f => [tab === 'cv' ? tr('source') : '', f]);
  drawPath(tab === 'cv' ? main.concat(rev ? [] : s.paths.pdf.map(f => ['PDF', f])) : main, s.root);
}
let tplList = [], tplCurrent = '';
async function setTemplate(name) {
  const r = await fetch('/set-template', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ t: target, template: name }) });
  const j = await r.json(); toast(j.message || (j.ok ? tr('switched') : tr('notSwitched'))); version = -1; tick(true);
}
function drawTemplates() {
  // Redrawn only when the CV, its template or the list changes; previews are cached per minute.
  const grid = $('tplgrid'), sig = JSON.stringify([target, tplCurrent, tplList.map(t => t.name), LANG]);
  if (grid.dataset.sig === sig) return; grid.dataset.sig = sig; grid.replaceChildren();
  const stamp = Math.floor(Date.now() / 60000);
  for (const t of tplList) {
    const card = el('button', 'tplcard' + (t.name === tplCurrent ? ' on' : '')), th = el('span', 'thumb'), img = el('img');
    img.loading = 'lazy'; img.alt = ''; img.src = '/tpl-preview?' + q({ t: target, n: t.name, v: stamp }); th.append(img);
    card.title = t.label + (t.description ? '\n' + t.description : '') + (t.name === tplCurrent ? '\n' + tr('inUse') : '');
    card.append(th, el('b', '', t.label));
    card.onclick = () => { if (t.name !== tplCurrent) setTemplate(t.name); };
    grid.append(card);
  }
}
function fillTemplates(list, current) {
  tplList = list; tplCurrent = current;
  const cur = list.find(t => t.name === current); $('tpllabel').textContent = cur ? cur.label : current || '?';
  drawTemplates();
  const nc = $('nctpl'), keep = nc.value, sig = list.map(t => t.name).join() + LANG;
  if (nc.dataset.sig === sig) return; nc.dataset.sig = sig;
  nc.replaceChildren(...list.map(t => { const o = el('option', '', t.label + (t.name === 'classic' ? tr('default') : '')); o.value = t.name; return o; }));
  nc.value = keep || current || 'classic';
}
$('draftbtn').onclick = redraft;
$('nccreate').onclick = createCase; $('nccancel').onclick = () => $('newcase').close(); $('genbtn').onclick = generate;
let cctx = null;
function checkSel() {
  const sel = getSelection(); if (!sel || sel.isCollapsed || !sel.rangeCount) return;
  const quote = sel.toString().replace(/\s+/g, ' ').trim(); if (quote.length < 2) return;
  const n = sel.anchorNode, host = n && (n.nodeType === 1 ? n : n.parentElement);
  if (!host || !host.closest('#view') || host.closest('#cbox') || host.closest('textarea, input, select, .pf-edit')) return;
  const sheet = host.closest('.sheet'), page = sheet ? [...$('view').querySelectorAll('.sheet')].indexOf(sheet) + 1 : 0;
  const source = isDoc(target) ? ({ 'doc/how': 'how', 'doc/prompt': 'prompt' }[target] || (target.endsWith('/raw') ? 'profile' : 'personal')) : (tab === 'cv' ? 'cv' : tab);
  const h1 = (() => { let n = host.closest('.md > *'); while (n) { if (n.tagName === 'H1') return n.textContent.trim(); n = n.previousElementSibling; } return ''; })();
  cctx = { quote, page, source, file: isDoc(target) ? h1 : '' };
  const sec = host.closest('[data-section]'); if (sec) { cctx.file = sec.dataset.file; cctx.section = sec.dataset.section; }
  const r = sel.getRangeAt(0).getBoundingClientRect(), box = $('cbox');
  $('cquote').textContent = '«' + (quote.length > 160 ? quote.slice(0, 160) + ' ...' : quote) + '»';
  box.classList.add('show'); $('ctext').value = '';
  const w = box.offsetWidth, h = box.offsetHeight;
  box.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 12)) + 'px';
  box.style.top = (r.bottom + h + 16 > innerHeight ? Math.max(8, r.top - h - 8) : r.bottom + 8) + 'px';
  $('ctext').focus();
}
function closeBox() { $('cbox').classList.remove('show'); cctx = null; }
async function sendComment() {
  const text = $('ctext').value.trim(); if (!text || !cctx) return;
  const body = { t: target, source: cctx.source, page: cctx.page, quote: cctx.quote, comment: text, revision: rev ? rev.hash : '', c: consC(), file: cctx.file || '', section: cctx.section || '' };
  const r = await fetch('/comment', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json(); toast(j.ok ? tr('sentToAssistant') : (j.message || tr('notStored')));
  if (j.ok) { closeBox(); getSelection().removeAllRanges(); loadComments(); }
}
let comments = [];
async function loadComments() {
  if (!target) return;
  try { comments = await (await fetch('/comments?' + q({ c: consC() }), { cache: 'no-store' })).json(); } catch (e) { return; }
  const open = comments.filter(c => c.status === 'open').length;
  for (const id of ['cmcount', 'cmcount2']) { $(id).hidden = !open; $(id).textContent = open; }
  $('genchip').hidden = !comments.some(c => c.status === 'open' && c.kind === 'generate' && c.target === target);
  $('genbtn').hidden = !target.includes('/applications/');
  drawComments();
}
function drawComments() {
  const pop = $('cmlist'), sig = JSON.stringify([comments, LANG]);
  if (pop.dataset.sig === sig) return; pop.dataset.sig = sig; pop.replaceChildren();
  const shown = comments.filter(c => c.status !== 'archived');
  if (!shown.length) { pop.append(el('div', 'empty', tr('noComments'))); return; }
  const act = async (id, status) => { await fetch('/comment-status', { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ c: consC(), id, status }) }); loadComments(); };
  for (const c of [...shown].sort((a, b) => (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1) || b.id - a.id)) {
    const d = el('div', 'cm' + (c.status === 'done' ? ' done' : ''));
    if (c.kind === 'generate') d.append(el('div', '', tr('genItem')));
    else if (c.kind === 'profile-interview') d.append(el('div', '', tr('interview', c.entry || tr('theProfile')) + (c.comment ? ': ' + c.comment : '')));
    else d.append(el('div', 'q', '«' + c.quote + '»'), el('div', '', c.comment));
    if (c.note) d.append(el('div', 'note', tr('assistant') + c.note));
    const meta = el('div', 'meta'); meta.append(el('span', '', (c.file || c.target).split('/').pop() + (c.section ? ' #' + c.section : '') + (c.page ? tr('page') + c.page : '')),
      el('span', '', new Date(c.time).toLocaleDateString(LOCALE())));
    const a = el('div', 'act'); const mk = (icn, title, fn) => { const b = el('button'); b.title = title; b.append(icon(icn)); b.onclick = fn; a.append(b); };
    mk(c.status === 'open' ? 'check' : 'back', c.status === 'open' ? tr('markDone') : tr('reopen'), () => act(c.id, c.status === 'open' ? 'done' : 'open'));
    mk('archive', tr('archive'), () => act(c.id, 'archived')); meta.append(a); d.append(meta); pop.append(d);
  }
}
// Text selection in the PDF, as in pdf.js's own viewer (TextLayerBuilder): each page's text layer
// ends in an .endOfContent backdrop. While selecting, it fills the page and sits right after the
// span the selection ends in, so dragging across the gap between two lines or columns extends the
// selection to the nearest text instead of jumping to the end of the page. Firefox does not need it.
const FIREFOX = /firefox/i.test(navigator.userAgent);
function resetEnd(tl) {
  const end = tl.querySelector('.endOfContent');
  if (end) { tl.append(end); end.style.width = end.style.height = ''; }
  tl.classList.remove('selecting');
}
const resetEnds = () => { document.querySelectorAll('.textLayer').forEach(resetEnd); prevRange = null; };
document.addEventListener('pointerdown', () => { pointerDown = true; });
document.addEventListener('pointerup', () => { pointerDown = false; resetEnds(); });
window.addEventListener('blur', () => { pointerDown = false; resetEnds(); });
document.addEventListener('keyup', () => { if (!pointerDown) resetEnds(); });
document.addEventListener('selectionchange', () => {
  const sel = getSelection(); if (!sel.rangeCount) { resetEnds(); return; }
  const range = sel.getRangeAt(0);
  for (const tl of document.querySelectorAll('.textLayer')) range.intersectsNode(tl) ? tl.classList.add('selecting') : resetEnd(tl);
  if (FIREFOX || !pointerDown) return;
  const atStart = prevRange && (range.compareBoundaryPoints(Range.END_TO_END, prevRange) === 0
                                || range.compareBoundaryPoints(Range.START_TO_END, prevRange) === 0);
  let a = atStart ? range.startContainer : range.endContainer;
  if (a.nodeType === Node.TEXT_NODE) a = a.parentNode;
  while (a.parentElement && !a.parentElement.matches('.textLayer, .markedContent')) a = a.parentElement;
  const tl = a.parentElement && a.parentElement.closest('.textLayer'), end = tl && tl.querySelector('.endOfContent');
  if (end && a !== end) {
    end.style.width = tl.clientWidth + 'px'; end.style.height = tl.clientHeight + 'px';
    a.parentElement.insertBefore(end, atStart ? a : a.nextSibling);
  }
  prevRange = range.cloneRange();
});
// A press in the gap between two lines lands on the text layer itself, and the browser then
// anchors the selection at the start of the page (Firefox) or does not select at all (Chrome).
// So a drag that starts in a gap is handled here: it starts at the nearest text and follows the
// pointer, with the same gap snapping while moving.
function textNodes(s) { const w = document.createTreeWalker(s, NodeFilter.SHOW_TEXT), out = []; while (w.nextNode()) out.push(w.currentNode); return out; }
function caretAt(tl, x, y) {
  let best = null, bd = Infinity;
  for (const s of tl.querySelectorAll('span')) {
    if (s.classList.contains('markedContent') || !s.textContent) continue;
    const r = s.getBoundingClientRect();
    const dy = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0, dx = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
    if (dy * 4 + dx < bd) { bd = dy * 4 + dx; best = [s, r]; }  // prefer the same line over the same column
  }
  if (!best) return null;
  const [s, r] = best, cx = Math.min(Math.max(x, r.left + 0.5), r.right - 0.5), cy = (r.top + r.bottom) / 2;
  const p = document.caretPositionFromPoint ? document.caretPositionFromPoint(cx, cy) : document.caretRangeFromPoint(cx, cy);
  const node = p && (p.offsetNode || p.startContainer), off = p && (p.offsetNode ? p.offset : p.startOffset);
  if (node && node.nodeType === Node.TEXT_NODE && s.contains(node)) return [node, off];
  const t = textNodes(s); return x > r.right ? [t[t.length - 1], t[t.length - 1].length] : [t[0], 0];
}
let gapDrag = null;
document.addEventListener('mousedown', e => {
  if (e.button !== 0 || e.shiftKey || e.detail > 1 || !e.target.closest) return;
  const tl = e.target.closest('.textLayer'); if (!tl || e.target.closest('span')) return;
  const c = caretAt(tl, e.clientX, e.clientY); if (!c) return;
  e.preventDefault(); gapDrag = c; getSelection().collapse(...c);
});
document.addEventListener('mousemove', e => {
  if (!gapDrag) return;
  const tl = document.elementFromPoint(e.clientX, e.clientY)?.closest('.textLayer'); if (!tl) return;
  const f = caretAt(tl, e.clientX, e.clientY); if (f) getSelection().setBaseAndExtent(...gapDrag, ...f);
});
document.addEventListener('mouseup', () => { gapDrag = null; });
document.addEventListener('mouseup', e => { if (!e.target.closest('#cbox') && !e.target.closest('.pop') && !e.target.closest('#rail')) setTimeout(checkSel, 10); });
document.addEventListener('mousedown', e => { if (!e.target.closest('#cbox') && !$('ctext').value.trim()) closeBox(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeBox(); $('pop').hidden = true; $('people').hidden = true; document.body.classList.remove('rail-open'); }
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && $('cbox').classList.contains('show')) sendComment(); });
$('csend').onclick = sendComment; $('ccancel').onclick = closeBox;
$('cmbtn').onclick = () => { document.body.classList.toggle('rail-open'); loadComments(); };
$('who').onclick = e => { e.stopPropagation(); $('people').hidden = !$('people').hidden; };
setInterval(loadComments, 5000);
$('q').addEventListener('input', () => highlight(true));
$('pdfbtn').onclick = e => { e.stopPropagation(); $('pdfmenu').hidden = !$('pdfmenu').hidden; };
document.addEventListener('click', e => { if (!e.target.closest('.menu')) $('pdfmenu').hidden = true; if (!e.target.closest('#people')) $('people').hidden = true; });
$('pdfmenu').addEventListener('click', e => { if (e.target.closest('.mi')) $('pdfmenu').hidden = true; });
$('finderbtn').onclick = () => fileAction('/reveal', tr('shownFinder'));
$('copybtn').onclick = () => fileAction('/copy', tr('pdfCopied'));
$('revbtn').onclick = openRevs; $('savebtn').onclick = saveRev; $('backbtn').onclick = () => { rev = null; version = -1; drawBanner(); tick(true); };
document.addEventListener('click', e => { if (!e.target.closest('#pop') && !e.target.closest('#revbtn')) $('pop').hidden = true; });
window.addEventListener('hashchange', () => { const t = decodeURIComponent(location.hash.slice(1)); if (t && t !== target) setTarget(t); });
fetch('/state', { cache: 'no-store' }).then(r => r.json()).then(s => {
  tree = s.tree;
  ctxC = tree[0] ? tree[0].person : '';
  if (!target || !(target.startsWith('doc/') || tree.some(c => target.startsWith(c.person + '/')))) target = tree[0] ? tree[0].person + (tree[0].base.length ? '/base/' + tree[0].base[0] : '/raw') : 'doc/how';
  if (!target.startsWith('doc/')) ctxC = target.split('/')[0];
  applyLang();
  document.body.classList.toggle('doc', isDoc(target));
  drawSide(); drawNav(); drawTitle(); tick(true); loadComments();
});
</script></body></html>"""


PROFILE_POSTS = ("/profile-save", "/profile-new", "/profile-remove", "/profile-flag", "/profile-restore", "/profile-request")


def profile_request(c, d):
    """'Ask for an interview': a request in feedback.json for the assistant to interview the person
    about one entry (or a new one), the way /generate queues a CV."""
    if not profiles.exists(c):
        return 404, {"ok": False, "message": say(c, "no-profile")}
    id_ = str(d.get("id", ""))
    if id_ and not pmodel.find(profiles.profile_dir(c), id_):
        return 404, {"ok": False, "message": say(c, "no-entry")}
    comment = str(d.get("comment", "")).strip()[:2000]
    with fb_lock:
        items = load_feedback(c)
        if id_ and any(i.get("kind") == "profile-interview" and i.get("entry") == id_ and i.get("status") == "open" for i in items):
            return 200, {"ok": True, "message": say(c, "queued")}
        rel = pmodel.find(profiles.profile_dir(c), id_) if id_ else ""
        files = profile_files(c)
        items.append({"id": max([i.get("id", 0) for i in items] + [0]) + 1, "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "target": f"{c}/raw", "kind": "profile-interview", "entry": id_,
                      "file": profile_api.shown_path(c, rel) if rel else (files[0] if files else ""), "source": "profile", "page": 0,
                      "revision": "", "quote": str(d.get("quote", ""))[:1500],
                      "comment": comment or say(c, "interview-default"), "status": "open", "note": ""})
        store_feedback(c, items)
    return 200, {"ok": True, "message": say(c, "interview")}


def draft_cv(k, force):
    """Rebuild k from the profile (tools/draft.py). (ok, message, needs_force)."""
    c, path = parse(k)
    kind, name = path.split("/", 1)
    target = draft.target(c, *(("generic", name) if kind == "applications" else (name, "")))
    if os.path.exists(target) and draft.edited(target) and not force:
        return False, "", True
    save_revision(c, f"Before drafting {path} from the profile")
    try:
        draft.write(c, **({"app": name} if kind == "applications" else {"variant": name}), force=True)
    except SystemExit as e:
        return False, str(e), False
    return True, say(c, "drafted"), False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj).encode(), "application/json")

    def file(self, f, ctype=None):
        try:
            with open(f, "rb") as fh:
                data = fh.read()
        except OSError:
            return self.send(404, b"not found", "text/plain")
        self.send(200, data, ctype or mimetypes.guess_type(f)[0] or "application/octet-stream")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        t = q.get("t", "")
        if u.path == "/":
            start = ""
            if START_C:
                start = f"{START_C}/applications/{START_APP}" if START_APP else f"{START_C}/base/{START_VARIANT or 'generic'}"
            page = PAGE.replace("__ICONS__", ICONS).replace("__START__", json.dumps(start)).replace("__FAVICON__", FAVICON)
            self.send(200, page.encode(), "text/html; charset=utf-8")
        elif u.path == "/state":
            body = {"tree": tree(), "ok": False, "files": []}
            if t and select(t):
                c, path = parse(t)
                d = case_dir(t)
                with lock:
                    body.update(state_of(t))
                body["ok"] = True
                body["files"] = [n for n in ("job-ad.md", "notes.md") if os.path.isfile(os.path.join(d, n))]
                body["files"] += ["form:" + n for n in forms(t)]
                body["formver"] = {n: max((os.path.getmtime(os.path.join(d, "forms", n + ext))
                                           for ext in (".docx", ".json") if os.path.isfile(os.path.join(d, "forms", n + ext))))
                                   for n in forms(t)}
                body["template"] = current_template(t)
                body["templates"] = template_list(c, body["template"])
                body["root"] = ROOT
                body["paths"] = {"cv": cv_files(t), "job-ad.md": cv_files(t, "job-ad.md"), "notes.md": cv_files(t, "notes.md"),
                                 "pdf": [os.path.relpath(pdf_path(t), ROOT)]}
                for n in forms(t):
                    body["paths"]["form:" + n] = cv_files(t, "form:" + n) + [os.path.relpath(
                        os.path.join(ROOT, "build", c, path, n + ".docx"), ROOT)]
                body["dirty"] = is_dirty(t)
            self.json(body)
        elif u.path == "/pdf" and valid(t):
            self.file(pdf_path(t), "application/pdf")
        elif u.path == "/rev-pdf" and valid(t) and re.fullmatch(r"[0-9a-f]{4,40}", q.get("r", "")):
            f = rev_pdf(t, q["r"])
            self.file(f, "application/pdf") if f else self.send(404, b"revision could not be built", "text/plain")
        elif u.path == "/revisions" and valid(t):
            self.json(revisions(t))
        elif u.path == "/tpl-preview" and valid(t) and re.fullmatch(r"[\w-]+", q.get("n", "")):
            f = tpl_preview(t, q["n"])
            self.file(f, "image/png") if f else self.send(404, b"no preview", "text/plain")
        elif u.path == "/doc" and DOC_RE.fullmatch(t):
            self.json(dict(doc_view(t), root=ROOT))
        elif u.path == "/file" and valid(t) and q.get("name") in ("job-ad.md", "notes.md"):
            self.file(os.path.join(case_dir(t), q["name"]), "text/plain; charset=utf-8")
        elif u.path in ("/form-pdf", "/form-docx") and valid(t) and q.get("name") in forms(t):
            try:
                f = form_pdf(t, q["name"]) if u.path == "/form-pdf" else form_docx(t, q["name"])
            except ValueError as e:
                return self.send(500, str(e).encode(), "text/plain; charset=utf-8")
            self.file(f, "application/pdf" if u.path == "/form-pdf" else
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif u.path == "/comments" and re.fullmatch(r"[\w.-]+", q.get("c", "")):
            self.json(load_feedback(q["c"]))
        elif u.path == "/favicon.svg":
            self.send(200, FAVICON.encode(), "image/svg+xml")
        elif u.path.startswith("/profile") and re.fullmatch(r"[\w.-]+", q.get("c", "")) and profiles.exists(q["c"]):
            c = q["c"]
            code, body = {"/profile": lambda: profile_api.data(c),
                          "/profile-state": lambda: profile_api.state(c),
                          "/profile-log": lambda: profile_api.log(c, q.get("id", "")),
                          "/profile-show": lambda: profile_api.show(c, q.get("id", ""), q.get("rev", "")),
                          "/profile-asof": lambda: profile_api.as_of(c, q.get("date", ""))}.get(u.path, lambda: (404, {"ok": False}))()
            self.json(body, code)
        elif u.path.startswith("/openself/"):
            f = os.path.realpath(os.path.join(OPENSELF_STATIC, u.path[len("/openself/"):]))
            if f.startswith(OPENSELF_STATIC + os.sep) and os.path.isfile(f):
                self.file(f, {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(os.path.splitext(f)[1]))
            else:
                self.send(404, b"not found", "text/plain")
        elif u.path.startswith("/static/"):
            f = os.path.realpath(os.path.join(STATIC, u.path[len("/static/"):]))
            if f.startswith(STATIC + os.sep):
                self.file(f)
            else:
                self.send(404, b"not found", "text/plain")
        elif u.path.startswith("/vendor/"):
            f = os.path.realpath(os.path.join(VENDOR, u.path[len("/vendor/"):]))
            if f.startswith(VENDOR + os.sep):
                self.file(f)
            else:
                self.send(404, b"not found", "text/plain")
        else:
            self.send(404, b"not found", "text/plain")

    def profile_post(self, path, data):
        c = str(data.get("c", ""))
        if not re.fullmatch(r"[\w.-]+", c) or not os.path.isdir(os.path.join(LOCAL, c)):
            return self.json({"ok": False, "message": say("", "unknown-person")}, 400)
        fn = {"/profile-save": profile_api.save, "/profile-new": profile_api.new, "/profile-remove": profile_api.remove,
              "/profile-flag": profile_api.flag, "/profile-restore": profile_api.restore, "/profile-request": profile_request}[path]
        code, body = fn(c, data)
        self.json(body, code)

    def do_POST(self):
        # Only the page itself may act: custom header (forces a CORS preflight) and a local Host.
        host_ok = self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        path = urlparse(self.path).path
        if path not in ("/save", "/reveal", "/copy", "/comment", "/comment-status", "/new-case", "/generate", "/set-template", "/draft") \
                + PROFILE_POSTS or self.headers.get("X-OpenVita") != "1" or not host_ok:
            return self.send(403, b"forbidden", "text/plain")
        size = int(self.headers.get("Content-Length", "0") or 0)
        if size > 2_000_000:
            return self.json({"ok": False, "message": "too large"}, 413)
        try:
            data = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            return self.json({"ok": False, "message": "bad request"}, 400)
        if not isinstance(data, dict):
            return self.json({"ok": False, "message": "bad request"}, 400)
        if path in PROFILE_POSTS:
            return self.profile_post(path, data)
        if path == "/save":
            c = str(data.get("c", ""))
            if not re.fullmatch(r"[\w.-]+", c) or not os.path.isdir(os.path.join(LOCAL, c)):
                return self.json({"ok": False, "message": say("", "unknown-person")}, 400)
            message = str(data.get("message", ""))[:200]
            ok, changed = save_revision(c, message or f"snapshot {time.strftime('%Y-%m-%d %H:%M')}")
            return self.json({"ok": ok, "message": say(c, ("saved" if changed else "unchanged") if ok else "not-saved")})
        if path == "/comment":
            t = str(data.get("t", ""))
            comment, quote = str(data.get("comment", "")).strip()[:2000], str(data.get("quote", "")).strip()[:1500]
            c = parse(t)[0] if not t.startswith("doc/") else str(data.get("c", ""))
            if not (valid(t) or DOC_RE.fullmatch(t)) or not comment or not quote \
                    or not re.fullmatch(r"[\w.-]+", c) or not os.path.isdir(os.path.join(LOCAL, c)):
                return self.json({"ok": False, "message": "bad request"}, 400)
            with fb_lock:
                items = load_feedback(c)
                source = str(data.get("source", "cv"))[:120]
                allowed = doc_files(t) if DOC_RE.fullmatch(t) else cv_files(t, source)
                hint = str(data.get("file", "")).strip().strip("`")
                items.append({"id": max([i.get("id", 0) for i in items] + [0]) + 1,
                              "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "target": t,
                              "file": hint if hint in allowed else allowed[0],
                              "source": source, "page": int(data.get("page") or 0),
                              "revision": re.sub(r"[^0-9a-f]", "", str(data.get("revision", "")))[:40],
                              "kind": "comment", "quote": quote, "comment": comment, "status": "open", "note": "",
                              **({"section": re.sub(r"[^\w-]", "", str(data.get("section", "")))[:40]} if data.get("section") else {})})
                store_feedback(c, items)
            return self.json({"ok": True})
        if path == "/new-case":
            c, name, ad = str(data.get("c", "")), str(data.get("name", "")).strip(), str(data.get("jobad", "")).strip()
            if not re.fullmatch(r"[\w.-]+", c) or not os.path.isdir(os.path.join(LOCAL, c)):
                return self.json({"ok": False, "message": say("", "unknown-person")}, 400)
            if not re.fullmatch(r"\d{4}-\d{2}-[\w.-]+", name) or len(ad) < 40:
                return self.json({"ok": False, "message": say(c, "name-or-ad")}, 400)
            tpl = str(data.get("template", ""))
            if tpl and tpl not in templates.names(c):
                return self.json({"ok": False, "message": say(c, "unknown-template")}, 400)
            made = run_make(["new", f"C={c}", f"APP={name}"] + ([f"TEMPLATE={tpl}"] if tpl else []))
            if made.returncode != 0:
                return self.json({"ok": False, "message": (made.stderr or made.stdout).strip().splitlines()[-1][:200]}, 400)
            with open(os.path.join(LOCAL, c, "applications", name, "job-ad.md"), "w") as fh:
                fh.write(f"# Job ad\n\nCustomer:\nRole:\nLink:\nDeadline:\n\n{ad}\n")
            return self.json({"ok": True, "target": f"{c}/applications/{name}"})
        if path == "/set-template":
            t, tpl = str(data.get("t", "")), str(data.get("template", ""))
            c = parse(t)[0] if valid(t) else ""
            if not valid(t) or tpl not in templates.names(c) or not os.path.isfile(src(t)):
                return self.json({"ok": False, "message": "bad request"}, 400)
            if current_template(t) == tpl:
                return self.json({"ok": True, "message": say(c, "same-template")})
            save_revision(c, f"Before switching {t.split('/', 1)[1]} to template {tpl}")
            try:
                draft.switch(c, src(t), tpl)
            except SystemExit as e:
                return self.json({"ok": False, "message": str(e) or say(c, "not-switched")})
            return self.json({"ok": True, "message": say(c, "switched", tpl=templates.find(tpl, c)["label"])})
        if path == "/draft":
            t = str(data.get("t", ""))
            if not valid(t):
                return self.json({"ok": False, "message": "bad request"}, 400)
            ok, message, needs_force = draft_cv(t, bool(data.get("force")))
            return self.json({"ok": ok, "message": message, "edited": needs_force})
        if path == "/generate":
            t = str(data.get("t", ""))
            if not valid(t) or not t.split("/")[1] == "applications" or not os.path.isfile(os.path.join(case_dir(t), "job-ad.md")):
                return self.json({"ok": False, "message": say(parse(t)[0] if valid(t) else "", "only-apps")}, 400)
            c, _ = parse(t)
            with fb_lock:
                items = load_feedback(c)
                if any(i.get("kind") == "generate" and i.get("target") == t and i.get("status") == "open" for i in items):
                    return self.json({"ok": True, "message": say(c, "queued")})
                items.append({"id": max([i.get("id", 0) for i in items] + [0]) + 1, "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "target": t, "kind": "generate", "file": cv_files(t, "job-ad.md")[0], "source": "job-ad.md", "page": 0, "revision": "",
                              "quote": say(c, "ad"), "comment": say(c, "generate"), "status": "open", "note": ""})
                store_feedback(c, items)
            return self.json({"ok": True, "message": say(c, "requested")})
        if path == "/comment-status":
            c = str(data.get("c", ""))
            if not re.fullmatch(r"[\w.-]+", c) or data.get("status") not in ("open", "done", "archived", "delete"):
                return self.json({"ok": False, "message": "bad request"}, 400)
            with fb_lock:
                items = load_feedback(c)
                if data["status"] == "delete":
                    items = [i for i in items if i.get("id") != data.get("id")]
                else:
                    for i in items:
                        if i.get("id") == data.get("id"):
                            i["status"] = data["status"]
                store_feedback(c, items)
            return self.json({"ok": True})
        t, r = str(data.get("t", "")), str(data.get("r", ""))
        f = current_pdf(t, r) if valid(t) and (not r or re.fullmatch(r"[0-9a-f]{4,40}", r)) else None
        c = parse(t)[0] if valid(t) else ""
        if not f:
            return self.json({"ok": False, "message": say(c, "no-pdf")}, 404)
        if sys.platform != "darwin":
            return self.json({"ok": False, "message": say(c, "macos")})
        if path == "/reveal":
            cmd = ["open", "-R", f]
        else:
            cmd = ["osascript", "-e", "on run argv", "-e", "set the clipboard to (POSIX file (item 1 of argv))", "-e", "end run", f]
        done = subprocess.run(cmd, capture_output=True, text=True)
        self.json({"ok": done.returncode == 0, "message": done.stderr.strip()[:200]})


if __name__ == "__main__":
    if START_C and START_APP and not os.path.isfile(src(f"{START_C}/applications/{START_APP}")):
        sys.exit(f"missing application {START_APP}")
    threading.Thread(target=watcher, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Workbench at {url}  (Ctrl+C to stop)", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    if not os.environ.get("OPENVITA_NO_BROWSER"):
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
