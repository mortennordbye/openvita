"""The workbench over HTTP, against a copy of the example profile on a free port: the Profile
endpoints (OpenSelf's API), drafting from the profile and switching templates."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
A = "2021-04-vestkraft-skymigrering"


class ServeProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.prof = os.path.join(cls.tmp, "ola", "profile")
        shutil.copytree(os.path.join(ROOT, "openself", "example"), cls.prof)
        os.makedirs(os.path.join(cls.tmp, "customers"))  # not a person: must be skipped
        with open(os.path.join(cls.tmp, "README.md"), "w") as f:
            f.write("x")
        cls.env = dict(os.environ, OPENVITA_LOCAL=cls.tmp, OPENVITA_NO_BROWSER="1", **GIT_ENV)
        cls.env.pop("OPENVITA_TEMPLATES", None)
        subprocess.run(["git", "init", "-q", cls.prof], check=True)
        subprocess.run(["git", "-C", cls.prof, "add", "-A"], check=True)
        subprocess.run(["git", "-C", cls.prof, "commit", "-qm", "profile: start [tool]"], check=True, env=cls.env)
        subprocess.run(["git", "init", "-q", os.path.join(cls.tmp, "ola")], check=True)
        with open(os.path.join(cls.tmp, "ola", ".gitignore"), "w") as f:
            f.write("/profile/\n")
        subprocess.run([sys.executable, os.path.join(TOOLS, "draft.py"), "ola"], check=True, env=cls.env, stdout=subprocess.DEVNULL)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.srv = subprocess.Popen([sys.executable, os.path.join(TOOLS, "serve.py"), "", "", "", str(cls.port)],
                                   env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                cls.get("/state")
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.kill()
        cls.srv.wait()
        cls.srv.stderr.close()
        shutil.rmtree(cls.tmp)

    @classmethod
    def get(cls, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}{path}") as r:
            return json.loads(r.read())

    def post(self, path, body, headers=None):
        h = {"X-OpenVita": "1", "Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(dict({"c": "ola"}, **body)).encode(), h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                data = e.read()
            return e.code, json.loads(data) if data.startswith(b"{") else {}

    def entry(self, id_):
        return next(e for e in self.get("/profile?c=ola")["entries"] if e["id"] == id_)

    def log(self):
        return subprocess.run(["git", "-C", self.prof, "log", "--format=%s"], capture_output=True, text=True).stdout.splitlines()

    def test_1_read(self):
        d = self.get("/profile?c=ola")
        self.assertTrue(d["ok"])
        self.assertEqual(len([e for e in d["entries"] if e["type"] == "assignment" and not e["removed"]]), 4)
        self.assertIn("Kubernetes", d["tech_names"])
        self.assertTrue(d["entries"][0]["file"].endswith(".md"))
        self.assertEqual(self.get("/profile-state?c=ola")["version"], d["version"])
        tree = self.get("/state")["tree"]
        self.assertEqual([(p["person"], p["profile"], p["lang"], p["base"]) for p in tree], [("ola", "profile", "nb", ["generic"])])

    def test_2_save_conflict_and_commit(self):
        e = self.entry(A)
        meta = dict(e["meta"], role="Arkitekt")
        code, j = self.post("/profile-save", {"id": A, "meta": meta, "sections": e["sections"], "base_sha": e["sha"]})
        self.assertEqual((code, j["ok"]), (200, True), j)
        self.assertEqual(self.log()[0], f"{A}: edited [owner]")
        again = self.entry(A)
        self.assertEqual(again["meta"]["role"], "Arkitekt")
        self.assertIn("Laget landingssonen i Terraform.", again["text"])
        code, j = self.post("/profile-save", {"id": A, "meta": meta, "sections": e["sections"], "base_sha": e["sha"]})
        self.assertEqual(code, 409)
        self.assertEqual(j["current_sha"], again["sha"])
        code, j = self.post("/profile-save", {"id": A, "meta": dict(meta, start="soon"), "sections": [], "base_sha": again["sha"]})
        self.assertEqual(code, 400)

    def test_3_new_flag_remove_restore(self):
        code, j = self.post("/profile-new", {"type": "assignment", "fields": {"kind": "client", "employment": "2021-03-fjordsky-seniorkonsulent",
                                             "customer": "Bergen Havn", "start": "2026-09", "end": "ongoing", "tech": ["Kubernetes"]},
                                             "sections": {"contribution": "Alt."}})
        self.assertEqual(code, 200, j)
        self.assertEqual(j["id"], "2026-09-bergen-havn")
        e = self.entry("2026-09-bergen-havn")
        self.assertEqual(e["meta"]["confidence"], "stated")

        e = self.entry(A)
        flag = next(f for f in e["flags"] if f["open"] and f["type"] == "question")
        code, j = self.post("/profile-flag", {"id": A, "raw": flag["raw"], "answer": "To.", "base_sha": e["sha"]})
        self.assertEqual(code, 200, j)
        self.assertIn("Svar: «To.»", self.entry(A)["text"])

        code, j = self.post("/profile-remove", {"id": "2022-01-intern-plattformkode", "reason": "test"})
        self.assertEqual(code, 200, j)
        self.assertTrue(self.entry("2022-01-intern-plattformkode")["removed"])

        items = self.get(f"/profile-log?c=ola&id={A}")["items"]
        first = items[-1]["rev"]
        self.assertIn("role: Skyarkitekt", self.get(f"/profile-show?c=ola&id={A}&rev={first}")["text"])
        code, j = self.post("/profile-restore", {"id": A, "rev": first})
        self.assertEqual(code, 200, j)
        self.assertEqual(self.entry(A)["meta"]["role"], "Skyarkitekt")
        asof = self.get("/profile-asof?c=ola&date=2099-12-31")
        self.assertTrue(asof["ok"])

    def test_4_outside_changes_are_kept(self):
        path = os.path.join(self.prof, "person.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("location: Bergen", "location: Voss"))
        e = self.entry("person")
        code, _ = self.post("/profile-save", {"id": "person", "meta": dict(e["meta"], title="Rådgiver"), "sections": e["sections"], "base_sha": e["sha"]})
        self.assertEqual(code, 200)
        self.assertEqual(self.log()[1], "profile: changes made outside the web app [tool]")

    def test_5_request_and_comment(self):
        code, j = self.post("/profile-request", {"id": A, "comment": "Spør om teamet"})
        self.assertEqual(code, 200, j)
        code, j = self.post("/profile-request", {"id": A, "comment": "igjen"})
        self.assertIn("Allerede", j["message"])
        file = self.entry(A)["file"]
        code, j = self.post("/comment", {"t": "ola/raw", "source": "profile", "quote": "Datasenteret", "comment": "x", "file": file, "section": "outcome"})
        self.assertEqual(code, 200)
        with open(os.path.join(self.tmp, "ola", "feedback.json"), encoding="utf-8") as f:
            items = json.load(f)
        self.assertEqual([i["kind"] for i in items], ["profile-interview", "comment"])
        self.assertEqual((items[1]["file"], items[1]["section"]), (file, "outcome"))

    def test_6_refused(self):
        self.assertEqual(self.post("/profile-save", {"id": A}, {"X-OpenVita": "0"})[0], 403)
        self.assertEqual(self.post("/profile-save", {"id": A}, {"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.post("/profile-save", {"id": "../../etc/passwd", "meta": {}})[0], 400)
        self.assertEqual(self.post("/profile-new", {"type": "person", "fields": {}})[0], 400)
        self.assertEqual(self.post("/profile-save", {"c": "../x", "id": A})[0], 400)
        mpath = os.path.join(self.prof, "openself.json")
        with open(mpath, encoding="utf-8") as f:
            manifest = f.read()
        try:
            with open(mpath, "w", encoding="utf-8") as f:
                f.write(manifest.replace('"readonly": false', '"readonly": true'))
            self.assertEqual(self.post("/profile-remove", {"id": A, "reason": "x"})[0], 403)
        finally:
            with open(mpath, "w", encoding="utf-8") as f:
                f.write(manifest)


    def test_7_templates_and_draft(self):
        s = self.get("/state?t=ola/base/generic")
        self.assertEqual(s["template"], "classic")
        self.assertEqual([t["name"] for t in s["templates"]], ["classic", "minimal", "sidebar"])
        code, j = self.post("/set-template", {"t": "ola/base/generic", "template": "sidebar"})
        self.assertEqual((code, j["ok"]), (200, True), j)
        cv = os.path.join(self.tmp, "ola", "base", "generic", "cv.html")
        with open(cv, encoding="utf-8") as f:
            self.assertIn("template:sidebar/cv.css", f.read())
        self.assertEqual(self.post("/set-template", {"t": "ola/base/generic", "template": "nope"})[0], 400)
        # an untouched draft is drafted again in the new template; once edited, a redraft asks first
        code, j = self.post("/draft", {"t": "ola/base/generic"})
        self.assertTrue(j["ok"], j)
        with open(cv, "a", encoding="utf-8") as f:
            f.write("<!-- edited -->\n")
        code, j = self.post("/draft", {"t": "ola/base/generic"})
        self.assertEqual((j["ok"], j["edited"]), (False, True))
        code, j = self.post("/draft", {"t": "ola/base/generic", "force": True})
        self.assertTrue(j["ok"], j)
        with open(cv, encoding="utf-8") as f:
            self.assertIn("template:sidebar/cv.css", f.read())
        log = subprocess.run(["git", "-C", os.path.join(self.tmp, "ola"), "log", "--format=%s"], capture_output=True, text=True).stdout
        self.assertIn("Before drafting base/generic from the profile", log)

    def test_8_templates_with_other_markup(self):
        fam = os.path.join(self.tmp, "ola", "templates", "fam")
        os.makedirs(fam)
        with open(os.path.join(fam, "template.json"), "w") as f:
            json.dump({"label": "Fam", "markup": "hand-2025"}, f)
        with open(os.path.join(fam, "cv.css"), "w") as f:
            f.write("body {}")
        cv = os.path.join(self.tmp, "ola", "base", "hand", "cv.html")
        os.makedirs(os.path.dirname(cv))
        with open(cv, "w", encoding="utf-8") as f:
            f.write('<html lang="nb"><link rel="stylesheet" href="template:fam/cv.css"><p>by hand</p></html>\n')
        # a hand-made CV keeps its own family first; the built-ins come as a fresh draft
        s = self.get("/state?t=ola/base/hand")
        self.assertEqual({t["name"]: t["fits"] for t in s["templates"]},
                         {"fam": True, "classic": False, "minimal": False, "sidebar": False})
        # a draft cannot be written in other markup, so a CV in openvita markup is not offered it
        s = self.get("/state?t=ola/base/generic")
        self.assertNotIn("fam", [t["name"] for t in s["templates"]])
        self.assertEqual(self.post("/draft", {"t": "ola/base/hand", "template": "nope", "force": True})[0], 400)
        code, j = self.post("/draft", {"t": "ola/base/hand", "template": "classic", "force": True})
        self.assertEqual((code, j["ok"]), (200, True), j)
        with open(cv, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("template:classic/cv.css", html)
        self.assertIn('<html lang="nb">', html)
        log = subprocess.run(["git", "-C", os.path.join(self.tmp, "ola"), "log", "--format=%s"], capture_output=True, text=True).stdout
        self.assertIn("Before drafting base/hand from the profile in template classic", log)

    def test_9_meeting_prep(self):
        code, j = self.post("/new-case", {"name": "2026-11-acme-platform", "jobad": "Acme looks for a platform engineer with Kubernetes."})
        self.assertEqual((code, j["ok"]), (200, True), j)
        t = j["target"]
        self.assertEqual(self.post("/prep", {"t": t, "include": []})[0], 400)
        self.assertEqual(self.post("/prep", {"t": t, "include": "points"})[0], 400)
        self.assertEqual(self.post("/prep", {"t": "ola/base/generic", "include": ["points"]})[0], 400)
        code, j = self.post("/prep", {"t": t, "meeting": "First interview, 45 min", "include": ["ask", "points", "nope"]})
        self.assertEqual((code, j["ok"]), (200, True), j)
        code, j = self.post("/prep", {"t": t, "include": ["points"]})
        self.assertIn("Allerede", j["message"])
        with open(os.path.join(self.tmp, "ola", "feedback.json"), encoding="utf-8") as f:
            items = json.load(f)
        preps = [i for i in items if i["kind"] == "prep"]
        self.assertEqual(len(preps), 1)
        self.assertEqual((preps[0]["include"], preps[0]["comment"], preps[0]["source"]), (["points", "ask"], "First interview, 45 min", "prep.md"))
        self.assertTrue(preps[0]["file"].endswith("applications/2026-11-acme-platform/prep.md"))
        watch = subprocess.Popen([sys.executable, os.path.join(TOOLS, "watch-feedback.py"), "ola"], env=self.env,
                                 stdout=subprocess.PIPE, text=True)
        try:
            lines = [watch.stdout.readline() for i in items if i["status"] == "open"]
        finally:
            watch.kill()
            watch.wait()
            watch.stdout.close()
        self.assertIn("MEETING PREP", "".join(lines))
        self.assertIn("include=points,ask: First interview, 45 min", "".join(lines))
        self.assertNotIn("prep.md", self.get("/state?" + urllib.parse.urlencode({"t": t}))["files"])
        with open(os.path.join(self.tmp, t.split("/", 1)[0], t.split("/", 1)[1], "prep.md"), "w", encoding="utf-8") as f:
            f.write("# Prep\n\n- Talking point\n")
        s = self.get("/state?" + urllib.parse.urlencode({"t": t}))
        self.assertIn("prep.md", s["files"])
        self.assertIn("prep.md", s["mdver"])
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/file?" + urllib.parse.urlencode({"t": t, "name": "prep.md"})) as r:
            self.assertIn("Talking point", r.read().decode())
        code, j = self.post("/comment", {"t": t, "source": "prep.md", "quote": "Talking point", "comment": "shorter"})
        self.assertEqual(code, 200, j)
        with open(os.path.join(self.tmp, "ola", "feedback.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)[-1]["file"].endswith("/prep.md"))


if __name__ == "__main__":
    unittest.main()
