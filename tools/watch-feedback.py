#!/usr/bin/env python3
"""Print one line for every open comment or request in local/<name>/feedback.json.

    make watch-feedback C=kari

Meant for an assistant such as Claude Code: run it as a background monitor while the workbench
(make serve) is open, and every line becomes a notification. Items that were already open when it
started are printed once first, then only new ones. AGENTS.md describes what to do with each line.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402

c = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    folder = profiles.person_dir(c)
except ValueError:
    folder = ""
if not folder or not os.path.isdir(folder):
    sys.exit("usage: make watch-feedback C=<name>")
path = os.path.join(folder, "feedback.json")


def open_items():
    try:
        with open(path) as fh:
            return {i["id"]: i for i in json.load(fh) if i.get("status") == "open"}
    except (OSError, ValueError):
        return None


def line(i, prefix):
    f = i.get("file") or i["target"]
    if i.get("kind") == "generate":
        return f"{prefix}TAILOR CV #{i['id']} [{i['target']}] file={f}: write the CV for this job ad (Tailoring in AGENTS.md, read tuning.md)"
    if i.get("kind") == "prep":
        return (f"{prefix}MEETING PREP #{i['id']} [{i['target']}] file={f} include={','.join(i.get('include') or [])}: "
                f"{i.get('comment') or '(no details about the meeting)'} (Preparing for a meeting in AGENTS.md, read tuning.md)")
    if i.get("kind") == "profile-interview":
        return (f"{prefix}PROFILE INTERVIEW #{i['id']} [{i['target']}] entry={i.get('entry') or '(new)'} file={f}: "
                f"{i['comment']}{' | about: ' + i['quote'][:200] if i.get('quote') else ''} "
                f"(onboard phase 3 for this entry, in the person's own words)")
    if i.get("section"):
        f += f"#{i['section']}"
    return (f"{prefix}NEW COMMENT #{i['id']} [{i['target']}] file={f} source={i['source']} page={i.get('page')} "
            f"rev={i.get('revision') or '-'} | selection: {i['quote'][:200]} | wish: {i['comment']}")


seen = set()
first = True
while True:
    cur = open_items()
    if cur is not None:
        for id_, i in cur.items():
            if id_ not in seen:
                seen.add(id_)
                print(line(i, "ALREADY OPEN: " if first else ""), flush=True)
        first = False
    time.sleep(1)
