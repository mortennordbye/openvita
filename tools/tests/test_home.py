"""A person's folder kept encrypted in an OpenSelf home: connect, push, pull on another machine."""
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import EXAMPLE, GIT_ENV, ROOT, LocalDir


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age is not installed")
class Home(LocalDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from openself import history, sync
        from openself.__main__ import make_home
        self.sync, self.history = sync, history
        key = os.path.join(self.tmp, "key.txt")
        with open(key, "w") as f:
            f.write(sync.new_key())
        os.environ["OPENSELF_IDENTITY"] = key
        os.environ.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0"})
        outside = tempfile.mkdtemp()  # a home lives outside local/
        self.addCleanup(shutil.rmtree, outside, True)
        self.home = os.path.join(outside, "home")
        make_home(self.home)
        p = os.path.join(self.home, "profile")
        shutil.copytree(EXAMPLE, p)
        subprocess.run(["git", "init", "-q", "-b", "main", p], check=True)
        history.commit(p, history.message("profile", "start", "tool"))
        sync.keys_init(self.home)

    def make_person(self, c="kari"):
        d = self.person(c)
        subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
        os.makedirs(os.path.join(d, "releases"))
        with open(os.path.join(d, "releases", "kari-v1.pdf"), "wb") as f:
            f.write(b"%PDF-1.7\n" + bytes(range(256)) * 50)
        os.makedirs(os.path.join(d, "templates", "mine"))
        with open(os.path.join(d, "templates", "mine", "template.json"), "w") as f:
            json.dump({"label": "Mine", "brand": {"name": "Quietfjord Group"}}, f)
        with open(os.path.join(d, "templates", "mine", "cv.css"), "w") as f:
            f.write("body {}")
        self.history.commit(d, self.history.message("kari", "first CV", "owner"))
        return d

    def test_connect_push_pull(self):
        d = self.make_person()
        target = self.profiles.connect_home("kari", self.home)
        self.assertTrue(os.path.islink(d))
        self.assertEqual(os.path.realpath(d), os.path.realpath(target))
        self.assertEqual(self.sync.vaults(self.home), ["cv"])
        self.assertEqual(self.profiles.profile_dir("kari"), os.path.join(os.path.realpath(self.home), "profile"))
        self.assertEqual(self.profiles.language("kari"), "nb")
        subjects = [c["subject"] for c in self.history.log(target)]
        self.assertIn("kari: first CV [owner]", subjects)  # the folder's own history came along
        self.assertIn("mine", self.templates.names("kari"))  # templates/ in the folder is searched

        r = self.sync.push(self.home)
        self.assertEqual(sorted(r["encrypted"]), ["cv", "profile"])
        with open(os.path.join(self.home, "cv.age"), "rb") as f:
            self.assertNotIn(b"%PDF", f.read())

        # Another machine: clone the home, pull, and link a fresh local/ to the vault.
        b = os.path.join(os.path.dirname(self.home), "b")
        subprocess.run(["git", "clone", "-q", self.home, b], check=True)
        self.assertEqual(self.sync.pull(b, download=False)["vaults"]["cv"]["result"], "cloned")
        os.environ["OPENVITA_LOCAL"] = os.path.join(self.tmp, "local-b")
        import profiles
        p2 = importlib.reload(profiles)
        p2.connect_home("kari", b)
        self.assertTrue(os.path.isfile(os.path.join(p2.person_dir("kari"), "releases", "kari-v1.pdf")))
        self.assertEqual(p2.profile_dir("kari"), os.path.join(os.path.realpath(b), "profile"))

    def test_refusals(self):
        with self.assertRaises(SystemExit):
            self.profiles.connect_home("kari", self.tmp)  # not a home
        d = self.make_person()
        os.makedirs(os.path.join(self.home, "cv"))
        with open(os.path.join(self.home, "cv", "x.txt"), "w") as f:
            f.write("already here\n")
        with self.assertRaises(SystemExit):
            self.profiles.connect_home("kari", self.home)  # both hold files
        self.assertFalse(os.path.islink(d))

    def test_render_mounts_and_guard(self):
        self.make_person()
        self.profiles.connect_home("kari", self.home)
        import render
        import guard
        r = importlib.reload(render)
        m = r.mounts("kari")
        real = os.path.realpath(os.path.join(self.home, "cv"))
        self.assertEqual(m[real], "/person/kari")
        self.assertEqual(r.inside(m, os.path.join(self.tmp, "kari", "base", "generic")), "/person/kari/base/generic")
        g = importlib.reload(guard)
        where = {w for _, w in g.needles()}
        self.assertIn("the brand name of template mine", where)


if __name__ == "__main__":
    unittest.main()
