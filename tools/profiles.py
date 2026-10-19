#!/usr/bin/env python3
"""OpenVita's link to each person's OpenSelf profile (the format in openself/).

    python3 tools/profiles.py path C              where C's profile lives
    python3 tools/profiles.py init C              create an empty one (make new-person does this)
    python3 tools/profiles.py connect C PATH      use an existing profile or OpenSelf home
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
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.environ.get("OPENVITA_LOCAL") or os.path.join(ROOT, "local")
CONFIG = "openvita.json"
RESERVED = ("customers",)  # folders in local/ that are not a person
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
    p = os.path.expanduser(str(p))
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(person_dir(c), p))


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
    elif a.cmd == "commit":
        print(commit(a.c, a.id, a.what, a.actor) or "nothing to commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
