import json
import os
import unittest

from helpers import ROOT, LocalDir


def make(folder, name, brand=None, css="body {}"):
    d = os.path.join(folder, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "template.json"), "w") as f:
        json.dump({"label": name.title(), **({"brand": brand} if brand else {})}, f)
    if css is not None:
        with open(os.path.join(d, "cv.css"), "w") as f:
            f.write(css)
    return d


class Templates(LocalDir, unittest.TestCase):
    def test_builtin(self):
        names = self.templates.names()
        self.assertEqual(names, ["classic", "minimal", "sidebar"])
        for n in names:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "templates", n, "cv.css")))

    def test_search_order_and_problems(self):
        company = os.path.join(self.tmp, "company")
        make(company, "acme")
        make(company, "classic", css="/* the company's own classic */")
        make(company, "broken", css=None)
        os.environ["OPENVITA_TEMPLATES"] = company
        own = make(self.tmp, "mine")  # a single template folder in the person's config
        self.person("ola")
        self.profiles.set_config("ola", templates=[own])
        found, problems = self.templates.discover("ola")
        self.assertEqual([t["name"] for t in found], ["mine", "acme", "classic", "minimal", "sidebar"])
        self.assertEqual(self.templates.find("classic", "ola")["dir"], os.path.realpath(os.path.join(company, "classic")))
        self.assertEqual(len(problems), 1)
        self.assertIn("no cv.css", problems[0])
        self.assertNotIn("mine", self.templates.names())  # other people do not see ola's

    def test_switch_and_brand(self):
        brand = {"name": "Acme AS", "logo": "assets/logo.svg", "url": "https://acme.example",
                 "email": "{first}.{last}@acme.example", "address": "Main St 1"}
        os.environ["OPENVITA_TEMPLATES"] = make(self.tmp, "acme", brand)
        acme, classic = self.templates.find("acme"), self.templates.find("classic")
        text = ('<link rel="stylesheet" href="template:classic/cv.css">\n' + self.templates.brand_html(classic))
        branded = self.templates.switch(text, acme)
        self.assertEqual(self.templates.current(branded), "acme")
        self.assertIn('src="template:acme/assets/logo.svg"', branded)
        self.assertIn("Acme AS", branded)
        back = self.templates.switch(branded, classic)
        self.assertEqual(back, text)
        self.assertEqual(self.templates.brand_contact(acme, {"name": "Åse Ødegård"})["email"], "ase.odegard@acme.example")

    def test_render_paths(self):
        import importlib
        import render
        render = importlib.reload(render)
        ext = make(self.tmp, "acme")
        os.environ["OPENVITA_TEMPLATES"] = ext
        m = render.mounts("")
        self.assertEqual(m[os.path.realpath(ext)], "/tpl/acme")
        self.assertEqual(m[os.path.realpath(self.tmp)], "/work/local")  # local/ outside the repo
        self.assertEqual(render.inside(m, os.path.join(self.tmp, "ola", "base")), "/work/local/ola/base")
        self.assertEqual(render.inside(m, os.path.join(ROOT, "build", "x.pdf")), "/work/build/x.pdf")
        out = render.resolved("", '<link href="template:acme/cv.css"><img src="template:nope/x.png">')
        self.assertEqual(out, '<link href="/tpl/acme/cv.css"><img src="template:nope/x.png">')


if __name__ == "__main__":
    unittest.main()
