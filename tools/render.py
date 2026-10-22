#!/usr/bin/env python3
"""HTML to PDF (and PNG previews) for one person's CV, with its template: links resolved.

    python3 tools/render.py pdf C SRC.html OUT.pdf
    python3 tools/render.py png OUT.pdf PREFIX [DPI]

WeasyPrint runs in the openvita Docker image (see Dockerfile). Templates can live outside this
repository, so every template the person can use is mounted read-only at /tpl/<name> and the
shared fonts at /tpl/_shared; `template:<name>/` in the CV becomes `/tpl/<name>/` in the HTML that
is piped to WeasyPrint. A template's CSS can always reach the shared fonts as
../_shared/. The person's profile is mounted read-only at /profile, so `profile:photos/...` in a
CV shows a photo from the profile (OpenSelf's photos/, see the Photo view). Set OPENVITA_RENDER=local to use a WeasyPrint and
pdftoppm installed on this machine instead of Docker.

tools/serve.py keeps a warm worker (tools/render-worker.py) running in the container, restarted
when the set of mounts changes. Each function returns (ok, error text).
"""

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles  # noqa: E402
import templates  # noqa: E402

ROOT = profiles.ROOT
IMAGE = "openvita"
LOCAL_MODE = os.environ.get("OPENVITA_RENDER") == "local"


def mounts(c):
    """{host folder: container folder} for the repository, local/ and every template C can use."""
    m = {os.path.realpath(ROOT): "/work"}
    local = os.path.realpath(profiles.LOCAL)
    if os.path.commonpath([os.path.realpath(ROOT), local]) != os.path.realpath(ROOT):
        m[local] = "/work/local"
    for p in sorted(os.listdir(local)) if os.path.isdir(local) else []:
        real = os.path.realpath(os.path.join(local, p))
        if os.path.isdir(real) and os.path.commonpath([local, real]) != local:
            m[real] = f"/person/{p}"  # local/<p> links into an OpenSelf home
    if profiles.exists(c):
        m[os.path.realpath(profiles.profile_dir(c))] = "/profile"
    m[os.path.realpath(templates.SHARED)] = "/tpl/_shared"
    for t in templates.discover(c)[0]:
        m[t["dir"]] = f"/tpl/{t['name']}"
    return m


def inside(m, path):
    """The container path of a host path, or None when it is not mounted."""
    path = os.path.realpath(path)
    best = max((h for h in m if os.path.commonpath([h, path]) == h and not m[h].startswith("/tpl/") and m[h] != "/profile"),
               key=len, default=None)
    # longest match wins, so a person's linked folder beats /work
    return None if best is None else m[best] + path[len(best):]


PROFILE_LINK = re.compile(r"""(["'(])profile:(photos/[\w./-]+)""")


def resolved(c, text, base="/tpl", profile="/profile"):
    """The CV text laid out by its template (templates.laid_out), with template: links pointing at
    base/<name>/ (the mounts, or a local mirror) and profile: links at the profile."""
    known = set(templates.names(c))
    text = templates.laid_out(c, text)
    text = PROFILE_LINK.sub(lambda m: f"{m.group(1)}{profile}/{m.group(2)}" if ".." not in m.group(2) else m.group(0), text)

    def to(match):
        name = match.group(1)
        return f"{base}/{name}/" if name in known else match.group(0)  # WeasyPrint reports a missing one
    return templates.LINK.sub(to, text)


def mirror(c):
    """Without Docker: a temporary folder laid out like /tpl (symlinks), so ../_shared/ works the same."""
    d = tempfile.mkdtemp(prefix="openvita-tpl-")
    os.symlink(templates.SHARED, os.path.join(d, "_shared"))
    for t in templates.discover(c)[0]:
        os.symlink(t["dir"], os.path.join(d, t["name"]))
    return d


def docker_args(m):
    args = ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}"]
    for host, cont in m.items():
        args += ["-v", f"{host}:{cont}" + (":ro" if cont.startswith("/tpl/") or cont == "/profile" else "")]
    return args + ["-w", "/work", IMAGE]


class Worker:
    """A long-lived container running tools/render-worker.py, so each build skips the start-up cost."""

    def __init__(self):
        self.proc, self.key = None, None

    def call(self, m, req):
        """True when the worker did it. False means use the slow path."""
        key = json.dumps(m, sort_keys=True)
        try:
            if self.proc is None or self.proc.poll() is not None or key != self.key:
                self.close()
                cmd = docker_args(m)
                cmd[2:2] = ["-i"]
                self.proc = subprocess.Popen(cmd + ["python", "/work/tools/render-worker.py"], cwd=ROOT, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
                self.key = key
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
            reply = self.proc.stdout.readline()
            if not reply:
                raise RuntimeError("worker closed")
            return json.loads(reply)
        except (OSError, ValueError, RuntimeError):
            self.close()
            return None

    def close(self):
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None


worker = Worker()
atexit.register(worker.close)


def pdf(c, src, out, warm=False):
    """Render src (a cv.html of person C) to out."""
    with open(src, encoding="utf-8") as fh:
        return pdf_text(c, fh.read(), os.path.dirname(os.path.abspath(src)), out, warm)


def pdf_text(c, text, base, out, warm=False):
    """Render CV text whose relative links start in folder base. The resolved HTML goes in on stdin
    with base as base URL, so nothing is written next to the CV."""
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if LOCAL_MODE:
        d = mirror(c)
        try:
            r = subprocess.run([sys.executable, "-c", "import sys, weasyprint; "
                                "weasyprint.HTML(string=sys.stdin.read(), base_url=sys.argv[1]).write_pdf(sys.argv[2])",
                                base + "/", out], input=resolved(c, text, "file://" + d, "file://" + (profiles.profile_dir(c) if profiles.exists(c) else "/nonexistent")),
                               capture_output=True, text=True)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        return r.returncode == 0, (r.stderr or "")[-3000:]
    m = mounts(c)
    cbase, cout = inside(m, base), inside(m, out)
    if not cbase or not cout:
        return False, f"{base} or {out} is outside the folders mounted in Docker"
    html = resolved(c, text)
    if warm:
        reply = worker.call(m, {"op": "pdf", "html": html, "base": cbase + "/", "out": cout})
        if reply and reply.get("ok"):
            return True, ""
    cmd = docker_args(m)
    cmd[2:2] = ["-i"]
    r = subprocess.run(cmd + ["weasyprint", "--base-url", cbase + "/", "-", cout], input=html, cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout or "")[-3000:]


def pdf_to_text(pdf_file):
    """(ok, the text of a PDF inside this repository, pages separated by form feeds)."""
    if LOCAL_MODE:
        r = subprocess.run(["pdftotext", "-layout", pdf_file, "-"], capture_output=True, text=True)
        return r.returncode == 0, r.stdout if r.returncode == 0 else r.stderr
    m = {ROOT: "/work"}
    r = subprocess.run(docker_args(m) + ["pdftotext", "-layout", inside(m, pdf_file), "-"], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, r.stdout if r.returncode == 0 else r.stderr


def png(pdf_file, prefix, dpi=110, first_only=False):
    """PNG of each page (or page 1 only) of a PDF inside this repository."""
    opts = ["-r", str(dpi)] + (["-f", "1", "-l", "1", "-singlefile"] if first_only else []) + ["-png"]
    if LOCAL_MODE:
        r = subprocess.run(["pdftoppm"] + opts + [pdf_file, prefix], capture_output=True, text=True)
        return r.returncode == 0, r.stderr
    m = {ROOT: "/work"}
    cin, cprefix = inside(m, pdf_file), inside(m, prefix)
    r = subprocess.run(docker_args(m) + ["pdftoppm"] + opts + [cin, cprefix], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def main(argv):
    if len(argv) == 4 and argv[0] == "pdf":
        ok, err = pdf(argv[1], argv[2], argv[3])
        if not ok:
            print(err, file=sys.stderr)
            return 1
        print(argv[3])
        return 0
    if len(argv) in (3, 4) and argv[0] == "png":
        ok, err = png(argv[1], argv[2], int(argv[3]) if len(argv) == 4 else 110)
        if not ok:
            print(err, file=sys.stderr)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
