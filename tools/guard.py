#!/usr/bin/env python3
"""The guard: local work never reaches the openvita repository.

    python3 tools/guard.py                  check what is staged and the last commit
    python3 tools/guard.py --hook pre-commit|pre-push   (run by the hooks; pre-push reads git's stdin)
    python3 tools/guard.py --history        every commit on HEAD (CI runs this on a fresh clone)
    python3 tools/guard.py --install        put the pre-commit and pre-push hooks in place

.gitignore keeps local/ and build/ out of `git add`, but `git add -f`, a moved folder or a copied
file gets past it. The guard refuses a commit or push when:

- a file is under local/ (except its READMEs and the customer template) or build/;
- a file looks like personal work wherever it is: cv.html, job-ad.md, notes.md, tuning.md,
  feedback.json, openvita.json, an OpenSelf profile (openself.json, person.md), a filled form,
  a PDF, or anything carrying the `openvita draft` stamp;
- a template folder other than the built-in ones (templates/classic, sidebar, minimal, _shared)
  or the example company appears: your own and your company's templates live outside the
  repository and are found through OPENVITA_TEMPLATES or openvita.json;
- a submodule other than openself is added (a profile or template repository linked in);
- a text file contains a value from this machine's private data: a connected profile's person
  (name, email, phone), employers and customers; a template's brand (name, web address, email
  domain, office address) or its name and label, for every template outside this repository;
  and every line of local/forbidden.txt (words you never want in the repository, such as your
  employer's name). Values that are also in OpenSelf's fictional example are skipped.

More paths can be allowed in .openvita/allow, one glob per line, reviewed in a pull request like
any other change. Anything git cannot read counts as a problem: the guard fails closed.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402
import templates  # noqa: E402
from openself import model  # noqa: E402

ROOT = profiles.ROOT
MARK = "openvita guard"
GITLINK = "160000"
ZERO = "0" * 40
LOCAL_OK = ("local/README.md", "local/customers/README.md", "local/customers/_template.md")
TEMPLATES_OK = ("templates/_shared/*", "templates/classic/*", "templates/sidebar/*", "templates/minimal/*",
                "examples/templates/example-company/*")
PERSONAL = ("cv.html", "job-ad.md", "notes.md", "tuning.md", "feedback.json", "openvita.json", "openself.json",
            "person.md", "forbidden.txt")
PERSONAL_EXT = (".pdf", ".docx", ".png", ".jpg", ".jpeg")
PERSONAL_OK = ("examples/templates/example-company/assets/*",)  # images a template ships
STAMP = "<!-- openvita draft "
SENSITIVE = {"person": ("name", "email", "phone"), "employment": ("employer",), "assignment": ("customer", "customers")}


def git(*args, data=False, stdin=None):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, input=stdin)
    if r.returncode:
        return None
    return r.stdout if data else r.stdout.decode("utf-8", "replace")


# ---- what counts as private on this machine -------------------------------------------------

def pattern(value):
    flags = re.IGNORECASE if len(value) >= 5 else 0
    return re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", flags)


def profile_values(root):
    prof = model.load_profile(root)
    for e in list(prof.entries.values()) + list(prof.removed.values()):
        for key in SENSITIVE.get(e.type, ()):
            for v in e.list(key):
                yield str(v).strip(), f"the {key} in a connected profile"


def needles():
    """[(pattern, where)] for this machine's private values. Empty in CI, where local/ is empty."""
    example = os.path.join(profiles.ROOT, "openself", "example")  # the one shipped with these tools
    fictional = {v.lower() for v, _ in profile_values(example)} if os.path.isdir(example) else set()
    values = []
    people = sorted(os.listdir(profiles.LOCAL)) if os.path.isdir(profiles.LOCAL) else []
    for c in people:
        try:
            if profiles.exists(c):
                values += list(profile_values(profiles.profile_dir(c)))
        except ValueError:
            continue
    for c in [""] + people:
        try:
            found = templates.discover(c)[0]
        except ValueError:
            continue
        for t in found:
            if os.path.commonpath([ROOT, t["dir"]]) == ROOT:
                continue  # in the repository already: public
            b = t.get("brand") or {}
            values += [(t["name"], "the name of a template outside the repository"),
                       (t["label"], "the label of a template outside the repository")]
            values += [(str(b[k]), f"the brand {k} of template {t['name']}") for k in ("name", "address") if b.get(k)]
            if b.get("url"):
                values.append((re.sub(r"^https?://(www\.)?", "", str(b["url"])).strip("/"), f"the brand url of template {t['name']}"))
            if "@" in str(b.get("email", "")):
                values.append((str(b["email"]).split("@", 1)[1], f"the brand email domain of template {t['name']}"))
    words = os.path.join(profiles.LOCAL, "forbidden.txt")
    if os.path.isfile(words):
        with open(words, encoding="utf-8") as f:
            values += [(w.strip(), "a word in local/forbidden.txt") for w in f if w.strip() and not w.startswith("#")]
    out, seen = [], set()
    for v, where in values:
        if len(v) < 3 or v.lower() in seen or v.lower() in fictional:
            continue
        seen.add(v.lower())
        out.append((pattern(v), where))
    return out


# ---- checking a set of files ----------------------------------------------------------------

def allow_list(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.startswith("#")]


def problems_in(files, read, allow, found):
    """Problems with {path: mode}; read(path) gives the bytes or None."""
    out = []
    extra = allow_list(allow)
    for f in sorted(files):
        name = f.rsplit("/", 1)[-1]
        allowed = any(fnmatch.fnmatch(f, p) for p in extra)
        if files[f] == GITLINK:
            if f != "openself" and not allowed:
                out.append(f"{f}: a submodule; only openself may be linked in")
            continue
        if f.startswith("local/") and f not in LOCAL_OK and not allowed:
            out.append(f"{f}: local work stays on this machine (local/ is never committed)")
            continue
        if f.split("/", 1)[0] in ("build", "out") and not allowed:
            out.append(f"{f}: generated output, never committed")
            continue
        if (f.startswith("templates/") or f.startswith("examples/templates/")) and not any(fnmatch.fnmatch(f, p) for p in TEMPLATES_OK) \
                and not allowed:
            out.append(f"{f}: not a built-in template; your own and your company's live outside the repository (OPENVITA_TEMPLATES)")
            continue
        personal = name in PERSONAL or name.lower().endswith(PERSONAL_EXT)
        if personal and not allowed and not any(fnmatch.fnmatch(f, p) for p in PERSONAL_OK) and not f.startswith("tools/vendor/"):
            out.append(f"{f}: looks like personal work ({name}); add it to .openvita/allow if it is meant to be shared")
            continue
        blob = read(f)
        if blob is None:
            out.append(f"{f}: could not be read, so it cannot be checked")
            continue
        if b"\0" in blob[:8000]:
            continue  # binary: fonts and vendored files; the path rules above cover them
        text = blob.decode("utf-8", "replace")
        if STAMP in text and f != "tools/draft.py" and f != "tools/guard.py" and not f.startswith("tools/tests/"):
            out.append(f"{f}: a drafted CV (it carries the openvita draft stamp)")
        hits = sorted({where for pat, where in found if pat.search(text)})
        if hits:
            out.append(f"{f}: contains private text ({', '.join(hits)})")
    return out


def listing(out):
    if out is None:
        return None
    files = {}
    for rec in out.split("\0"):
        if "\t" in rec:
            meta, path = rec.split("\t", 1)
            files[path] = meta.split()[0]
    return files


def check_staged(found):
    files = listing(git("ls-files", "-s", "-z"))
    if files is None:
        return ["could not read the index, so it cannot be checked"]
    allow = git("show", ":.openvita/allow")
    return problems_in(files, lambda p: git("show", f":{p}", data=True), allow, found)


def check_commit(rev, found):
    files = listing(git("ls-tree", "-r", "-z", rev))
    if files is None:
        return [f"{rev[:7]}: could not read the commit, so it cannot be checked"]
    allow = git("show", f"{rev}:.openvita/allow")
    return [f"{rev[:7]}: {p}" for p in problems_in(files, lambda p: git("show", f"{rev}:{p}", data=True), allow, found)]


def outgoing(stdin_text):
    revs, bad = [], []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:
            continue
        local, remote = parts[1], parts[3]
        out = git("rev-list", f"{remote}..{local}") if remote != ZERO else None
        if out is None:
            out = git("rev-list", local, "--not", "--remotes")
        if out is None:
            bad.append(f"{local[:7]}: could not list the commits to push, so they cannot be checked")
        else:
            revs += out.split()
    return revs, bad


def check(hook=None, stdin_text="", history=False):
    found = needles()
    if history:
        out = git("rev-list", "HEAD")
        return ["could not list the history"] if out is None else [p for r in out.split() for p in check_commit(r, found)]
    if hook == "pre-commit":
        return check_staged(found)
    if hook == "pre-push":
        revs, out = outgoing(stdin_text)
        return out + [p for r in revs for p in check_commit(r, found)]
    head = git("rev-parse", "HEAD")
    return check_staged(found) + (check_commit(head.strip(), found) if head else [])


HOOK = """#!/bin/sh
# {mark}: refuses a commit or push that carries local work. Installed by tools/guard.py --install
# (make hooks; make serve, new-person and connect install it too).
root=$(git rev-parse --show-toplevel)
exec python3 "$root/tools/guard.py" --hook {name}
"""


def install():
    hooks = git("rev-parse", "--git-path", "hooks")
    if hooks is None:
        return []
    hooks = hooks.strip()
    hooks = hooks if os.path.isabs(hooks) else os.path.join(ROOT, hooks)
    os.makedirs(hooks, exist_ok=True)
    skipped = []
    for name in ("pre-commit", "pre-push"):
        path = os.path.join(hooks, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                if MARK not in f.read():
                    skipped.append(path)
                    continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(HOOK.format(mark=MARK, name=name))
        os.chmod(path, 0o755)
    return skipped


def main(argv):
    if "--install" in argv:
        for path in install():
            print(f"guard: left your own hook alone: {path}; call tools/guard.py --hook from it", file=sys.stderr)
        return 0
    hook = argv[argv.index("--hook") + 1] if "--hook" in argv else None
    stdin_text = sys.stdin.read() if hook == "pre-push" else ""
    problems = check(hook, stdin_text, "--history" in argv)
    if problems:
        print("openvita guard: refused, nothing was committed or pushed.", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("Unstage it (git restore --staged <file>) or move it to local/. See tools/guard.py.", file=sys.stderr)
        return 1
    if not hook:
        print("openvita guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
