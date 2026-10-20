"""The guard against a scratch repository: what it refuses, and that it stays quiet on clean work."""
import importlib
import json
import os
import shutil
import subprocess
import unittest

from helpers import GIT_ENV, LocalDir


class Guard(LocalDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import guard
        self.g = importlib.reload(guard)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.g.ROOT = self.repo
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.write("README.md", "# OpenVita\n")
        self.commit()

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def add(self, *rels):
        subprocess.run(["git", "-C", self.repo, "add", "-f", *rels], check=True)

    def commit(self):
        self.add("-A")
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "x"], check=True, env=dict(os.environ, **GIT_ENV))

    def staged(self):
        return self.g.check("pre-commit")

    def test_clean(self):
        self.write("tools/x.py", "print('hi')\n")
        self.write("local/README.md", "# Local\n")
        self.add("tools/x.py", "local/README.md")
        self.assertEqual(self.staged(), [])

    def test_paths(self):
        for rel in ("local/kari/base/generic/cv.html", "build/kari/x.pdf", "templates/acme/cv.css",
                    "examples/templates/acme/cv.css", "docs/cv.html", "docs/job-ad.md", "docs/prep.md", "some/openself.json", "x/form.docx"):
            self.write(rel, "x\n")
            self.add(rel)
        problems = "\n".join(self.staged())
        for rel in ("local/kari", "build/kari", "templates/acme", "examples/templates/acme", "docs/cv.html",
                    "docs/job-ad.md", "docs/prep.md", "some/openself.json", "x/form.docx"):
            self.assertIn(rel, problems)

    def test_allow_file(self):
        self.write("docs/cv.html", "<p>a sample</p>\n")
        self.write(".openvita/allow", "docs/cv.html\n")
        self.add("docs/cv.html", ".openvita/allow")
        self.assertEqual(self.staged(), [])

    def test_draft_stamp_and_words(self):
        self.write("docs/sample.html", "<!-- openvita draft 0123456789ab -->\n<html></html>\n")
        os.makedirs(os.path.join(self.tmp, "x"), exist_ok=True)
        with open(os.path.join(self.tmp, "forbidden.txt"), "w") as f:
            f.write("# words\nAcme Corp\n")
        self.write("docs/about.md", "Built at ACME CORP.\n")
        self.add("docs/sample.html", "docs/about.md")
        problems = "\n".join(self.staged())
        self.assertIn("docs/sample.html: a drafted CV", problems)
        self.assertIn("docs/about.md: contains private text (a word in local/forbidden.txt)", problems)

    def test_profile_and_brand_values(self):
        from helpers import EXAMPLE
        prof = os.path.join(self.tmp, "prof")
        shutil.copytree(EXAMPLE, prof)
        path = os.path.join(prof, "person.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("Ola Eksempel", "Kari Hansen-Real"))
        self.person("kari", prof)
        company = os.path.join(self.tmp, "company", "brightco")
        os.makedirs(company)
        with open(os.path.join(company, "template.json"), "w") as f:
            json.dump({"label": "Brightco CV", "brand": {"name": "Brightco Group", "email": "{first}@brightco.example"}}, f)
        with open(os.path.join(company, "cv.css"), "w") as f:
            f.write("body {}")
        os.environ["OPENVITA_TEMPLATES"] = os.path.dirname(company)
        self.write("docs/a.md", "Thanks to Kari Hansen-Real.\n")
        self.write("docs/b.md", "Mail us at someone@brightco.example\n")
        self.write("docs/c.md", "Fjordsky AS is fictional and fine.\n")  # also in OpenSelf's example
        self.add("docs/a.md", "docs/b.md", "docs/c.md")
        problems = "\n".join(self.staged())
        self.assertIn("docs/a.md: contains private text (the name in a connected profile)", problems)
        self.assertIn("docs/b.md: contains private text", problems)
        self.assertNotIn("docs/c.md", problems)

    def test_history_and_hooks(self):
        self.write("local/kari/tuning.md", "x\n")
        self.commit()  # committed without the hook
        self.assertTrue(any("local/kari/tuning.md" in p for p in self.g.check(history=True)))
        self.assertEqual(self.g.install(), [])
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        with open(hook) as f:
            self.assertIn("openvita guard", f.read())


if __name__ == "__main__":
    unittest.main()
