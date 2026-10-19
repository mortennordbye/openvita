#!/usr/bin/env python3
"""A warm WeasyPrint for the workbench. Runs inside the openvita container.

Reads one JSON request per line on stdin and answers with one JSON line on stdout:

    {"op": "pdf", "html": "<!doctype html>...", "base": "/work/local/<c>/base/generic/", "out": "/work/build/.../x.pdf"}

Importing WeasyPrint and loading the fonts once per session, instead of once per build, takes a
rebuild from about 0.7 s to about 0.25 s. tools/render.py starts it and falls back to a one-off
container if it is not available.
"""
import json
import sys

import weasyprint

for line in sys.stdin:
    try:
        req = json.loads(line)
        if req["op"] != "pdf":
            raise ValueError("unknown op")
        weasyprint.HTML(string=req["html"], base_url=req["base"]).write_pdf(req["out"])
        print(json.dumps({"ok": True}), flush=True)
    except Exception as e:  # keep serving after a bad CV
        print(json.dumps({"ok": False, "error": str(e)[:500]}), flush=True)
