#!/usr/bin/env python3
"""OpenVita's link to each person's OpenSelf profile (the format in openself/).

    python3 tools/profiles.py path C              where C's profile lives
    python3 tools/profiles.py init C              create an empty one (make new-person does this)
    python3 tools/profiles.py connect C PATH      use an existing profile or OpenSelf home
    python3 tools/profiles.py home C HOME [VAULT]  keep C's folder encrypted in an OpenSelf home
    python3 tools/profiles.py commit C ID WHAT [--actor owner|claude|tool]

The profile is found through local/<c>/openvita.json, {"profile": "<path>"}, relative to the
person's folder, absolute, or starting with ~. Without it, it is local/<c>/profile/. The path may
be a profile folder (it has openself.json) or an OpenSelf home made from openself-template (its
profile/ folder has openself.json). Inside the person's folder the profile is its own git
repository, ignored by the folder's own repository, so its history can travel without the CVs.

The same file holds the person's other settings:

    {"profile": "~/my-openself", "templates": ["~/work/cv-templates"], "language": "en"}
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.environ.get("OPENVITA_LOCAL") or os.path.join(ROOT, "local")
CONFIG = "openvita.json"
RESERVED = ("customers", ".assistant")  # folders in local/ that are not a person
ASSISTANT_STALE = 5  # seconds without a heartbeat before the workbench says no assistant is connected
sys.path.insert(0, os.path.join(ROOT, "openself"))

try:
    from openself import history, index, model, write  # noqa: E402
except ImportError:
    sys.exit("openself/ is empty: run `git submodule update --init` in the openvita folder")

LANGUAGES = ["en", "nb"]


def person_dir(c):
    if not re.fullmatch(r"[\w.-]+", c) or c in RESERVED:
        raise ValueError(f"bad name {c!r}")
    return os.path.join(LOCAL, c)


def assistant_file(c):
    """Heartbeat of `make watch-feedback C=<c>`: proof an assistant session is listening."""
    person_dir(c)  # checks the name
    return os.path.join(LOCAL, ".assistant", f"{c}.json")


def config(c):
    try:
        with open(os.path.join(person_dir(c), CONFIG), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_config(c, **values):
    data = config(c)
    data.update(values)
    os.makedirs(person_dir(c), exist_ok=True)
    write.write_atomic(os.path.join(person_dir(c), CONFIG), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def resolve(c, p):
    """A path from C's config: absolute, ~, or relative to C's folder where it really is (the folder
    may be a link into an OpenSelf home, see connect_home)."""
    p = os.path.expanduser(str(p))
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(real_dir(c), p))


def real_dir(c):
    """C's folder where it really is: the folder, or what a link in local/ points to."""
    d = person_dir(c)
    return os.path.realpath(d) if os.path.islink(d) else d


def as_profile(p):
    """The profile folder for p: p itself, or p/profile when p is an OpenSelf home."""
    if not os.path.isfile(os.path.join(p, model.MANIFEST)) and os.path.isfile(os.path.join(p, "profile", model.MANIFEST)):
        return os.path.join(p, "profile")
    return p


def profile_dir(c):
    return as_profile(resolve(c, config(c).get("profile") or "profile"))


def exists(c):
    try:
        return os.path.isfile(os.path.join(profile_dir(c), model.MANIFEST))
    except ValueError:  # not a person's folder (customers/, README.md)
        return False


def readonly(c):
    return bool(model.read_manifest(profile_dir(c)).get("readonly"))


def language(c):
    """The CV language: the config's, else the profile's first language, else English."""
    lang = config(c).get("language")
    if not lang and exists(c):
        lang = model.load_profile(profile_dir(c)).lang
    return lang if lang in ("en", "nb") else "en"


def ignore_in_person_repo(c):
    """The profile has its own history, so the person's repository must not track it (git would
    otherwise record it as an empty submodule link)."""
    d, p = person_dir(c), profile_dir(c)
    if os.path.commonpath([d, p]) != d:
        return
    line = "/" + os.path.relpath(p, d).replace(os.sep, "/") + "/"
    gi = os.path.join(d, ".gitignore")
    lines = []
    if os.path.exists(gi):
        with open(gi, encoding="utf-8") as f:
            lines = f.read().splitlines()
    if line not in lines:
        with open(gi, "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1] else "") + line + "\n")


def init(c):
    p = profile_dir(c)
    write.init(p, owner="", languages=LANGUAGES, git=True)
    ignore_in_person_repo(c)
    history.commit(p, history.message("profile", "created", "tool"))
    return p


def connect(c, path):
    """Point C at an existing profile or OpenSelf home. Checks it loads before writing the config."""
    target = resolve(c, path)
    p = as_profile(target)
    if not os.path.isfile(os.path.join(p, model.MANIFEST)):
        raise SystemExit(f"no OpenSelf profile at {p} (expected {model.MANIFEST} there or in profile/)")
    prof = model.load_profile(p)
    if prof.errors:
        print(f"warning: {len(prof.errors)} entries do not parse; run `./self lint` in the profile", file=sys.stderr)
    if str(path).startswith("~"):
        stored = str(path)
    elif all(os.path.commonpath([ROOT, x]) == ROOT for x in (target, person_dir(c))):  # both in openvita: relative, so it can move
        stored = os.path.relpath(target, person_dir(c))
    else:
        stored = target
    set_config(c, profile=stored)
    return p


def connect_home(c, home, vault="cv"):
    """Keep C's whole folder (CVs, applications, releases, photos, templates/) in a vault of an
    OpenSelf home, so `openself push` there encrypts every version of it and `pull` brings it to
    another machine. The folder moves into <home>/<vault>/ with its history, local/<c> becomes a
    link to it, and the profile is the home's. On a machine that pulled the vault, this only links."""
    from openself import sync
    home = os.path.realpath(os.path.expanduser(home))
    if not sync.is_home(home):
        raise SystemExit(f"{home} is not an OpenSelf home (no .openself/); make one from openself-template")
    if not os.path.isfile(os.path.join(home, "profile", model.MANIFEST)):
        raise SystemExit(f"no profile in {home}/profile yet: run ./self pull (or create it) there first")
    d, target = person_dir(c), os.path.join(home, vault)
    if os.path.islink(d):
        if os.path.realpath(d) == os.path.realpath(target):
            return target
        raise SystemExit(f"{d} already links to {os.path.realpath(d)}")
    has_work = os.path.isdir(d) and any(n not in (".DS_Store",) for n in os.listdir(d))
    vault_empty = not os.path.isdir(target) or not [n for n in os.listdir(target) if n != ".git"]
    if has_work and not vault_empty:
        raise SystemExit(f"both {d} and {target} hold files; merge them by hand, then run this again")
    if has_work and os.path.isdir(os.path.join(d, "profile")) and not os.path.islink(os.path.join(d, "profile")) \
            and os.listdir(os.path.join(d, "profile")):
        raise SystemExit(f"{d}/profile holds a profile of its own; the home's profile/ is used from now on. "
                         f"Move what you need into {home}/profile first, then remove {d}/profile")
    try:
        if has_work:
            if not history.is_repo(d):
                subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
            if os.path.isdir(target):
                shutil.rmtree(target)  # only openself's empty start; the folder brings its own history
            shutil.move(d, target)
        sync.add_vault(home, vault)
    except sync.SyncError as e:
        raise SystemExit(str(e))
    history.commit(target, history.message(vault, "moved into the OpenSelf home", "tool"))
    os.makedirs(os.path.dirname(d), exist_ok=True)
    os.symlink(target, d)
    set_config(c, profile="../profile")
    return target


def commit(c, id_, what, actor):
    p = profile_dir(c)
    index.write_all(p)
    return history.commit(p, history.message(id_, what, actor))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path").add_argument("c")
    sub.add_parser("init").add_argument("c")
    p = sub.add_parser("connect")
    p.add_argument("c"); p.add_argument("path")
    p = sub.add_parser("home")
    p.add_argument("c"); p.add_argument("home"); p.add_argument("vault", nargs="?", default="cv")
    p = sub.add_parser("commit")
    p.add_argument("c"); p.add_argument("id"); p.add_argument("what")
    p.add_argument("--actor", default="claude", choices=history.ACTORS)
    a = ap.parse_args(argv)
    if a.cmd == "path":
        print(profile_dir(a.c))
    elif a.cmd == "init":
        if exists(a.c):
            print(f"profile already exists: {profile_dir(a.c)}")
        else:
            print(f"profile created: {init(a.c)}")
    elif a.cmd == "connect":
        path = a.path if a.path.startswith("~") else os.path.abspath(a.path)  # relative to where it was typed
        print(f"{a.c} now uses the profile at {connect(a.c, path)}")
    elif a.cmd == "home":
        target = connect_home(a.c, a.home, a.vault)
        print(f"{a.c}'s folder is now {target} (local/{a.c} links there), encrypted as {a.vault}.age by `make push` in the home")
    elif a.cmd == "commit":
        print(commit(a.c, a.id, a.what, a.actor) or "nothing to commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
