"""The workbench's Profile endpoints: OpenSelf's web API (openself/openself/web/api.py) for the
person's profile, found through tools/profiles.py. Each function returns (http status, json).
"""

import os

import profiles
from openself.web import api


def root_of(c):
    return profiles.profile_dir(c)


def shown_path(c, rel):
    """The path a comment's `file` gets: repo-relative when the profile is inside the repo."""
    p = profiles.profile_dir(c)
    base = os.path.relpath(p, profiles.ROOT) if os.path.commonpath([profiles.ROOT, p]) == profiles.ROOT else p
    return f"{base}/{rel}"


def data(c):
    return api.data(root_of(c), shown_path(c, ""))


def state(c):
    return api.state(root_of(c))


def log(c, id_=""):
    return api.log(root_of(c), id_)


def show(c, id_, rev):
    return api.show(root_of(c), id_, rev)


def as_of(c, date):
    return api.as_of(root_of(c), date, shown_path(c, ""))


def save(c, d):
    return api.save(root_of(c), d)


def new(c, d):
    return api.new(root_of(c), d)


def remove(c, d):
    return api.remove(root_of(c), d)


def flag(c, d):
    return api.flag(root_of(c), d)


def restore(c, d):
    return api.restore(root_of(c), d)
