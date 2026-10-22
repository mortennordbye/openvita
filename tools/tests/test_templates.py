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
        out = render.resolved("", '<img src="profile:photos/edits/cv.jpg"><img src="profile:photos/../person.md">')
        self.assertEqual(out, '<img src="/profile/photos/edits/cv.jpg"><img src="profile:photos/../person.md">')

    CV = ('<html><head><link rel="stylesheet" href="template:acme/cv.css"></head><body>\n'
          '<!-- brand --><div class="brand"><img class="brand-logo" src="x.svg"></div><!-- /brand -->\n'
          '<div class="photo"><img src="p.jpg"></div>\n'
          '<header class="header"><h1 class="name">Ola</h1></header>\n'
          '<section class="profile"><p>About.</p></section>\n'
          '<aside class="sidebar main"><ul class="keys"><li>Azure</li></ul></aside>\n'
          '<aside class="sidebar social"><p class="github">gh</p></aside>\n'
          '<section class="edu"><div class="entry"><h3>Bachelor</h3></div></section>\n'
          '<!-- page 2 -->\n<h2 class="page-title">Experience</h2>\n'
          '<section class="timeline experience"><div class="entry"><h3>Consultant</h3><br></div></section>\n'
          '<p class="note">Something of my own.</p>\n'
          '</body></html>\n')

    def test_blocks(self):
        found = self.templates.blocks(self.CV.split("<body>")[1].split("</body>")[0])
        self.assertEqual([n for n, _ in found], ["brand", "photo", "header", "profile", "sidebar-main", "social", "edu",
                                                 "experience", ""])
        self.assertEqual("".join(s for _, s in found), self.CV.split("<body>")[1].split("</body>")[0])  # nothing lost
        self.assertTrue(dict(found)["experience"].lstrip().startswith('<!-- page 2 -->\n<h2 class="page-title">'))
        self.assertIsNone(self.templates.blocks("<section><p>open</section>"))  # unbalanced: no layout

    def test_compose(self):
        layout = ('<!-- slot: brand -->\n<div class="top" data-slot="photo header"></div>\n'
                  '<div class="cols"><div class="side" data-slot="sidebar"></div>'
                  '<div class="main" data-slot="edu highlight profile"></div></div>\n'
                  '<div class="hl" data-slot="highlight"></div>\n<!-- slot: experience -->\n')
        out = self.templates.compose(self.CV, layout)
        body = out.split("<body>")[1]
        order = [body.index(s) for s in ('class="brand"', 'class="top"', 'class="photo"', 'class="name"', 'class="side"',
                                         'sidebar main', 'sidebar social', 'class="main"', 'class="edu"', 'class="profile"',
                                         'page-title', 'class="note"')]
        self.assertEqual(order, sorted(order))  # the layout's order, slot by slot; the rest after it
        self.assertNotIn('class="hl"', out)  # no highlight in the CV: its wrapper is left out
        self.assertNotIn("data-slot", out)
        for piece in ("About.", "Azure", "gh", "Bachelor", "Consultant", "Something of my own."):
            self.assertEqual(out.count(piece), 1, piece)
        # a rest slot takes what no other slot took, where it stands
        out = self.templates.compose(self.CV, '<!-- slot: header -->\n<main><!-- slot: rest --></main>\n<!-- slot: experience -->')
        self.assertLess(out.index('class="name"'), out.index("<main>"))
        self.assertLess(out.index("<main>"), out.index("About."))
        self.assertLess(out.index("Something of my own."), out.index("</main>"))
        self.assertLess(out.index("</main>"), out.index("Consultant"))
        self.assertEqual(self.templates.compose("<p>no body</p>", layout), "<p>no body</p>")

    def test_layout_problems_and_laid_out(self):
        errors, warnings = self.templates.layout_problems('<!-- slot: header --><div data-slot="hedaer header"></div>')
        self.assertEqual(len(errors), 2)  # an unknown slot, and header twice
        errors, warnings = self.templates.layout_problems("<!-- slot: header sidebar -->")
        self.assertEqual(errors, [])
        self.assertIn("they go after the layout", warnings[0])
        self.assertNotIn("social", warnings[0])  # "sidebar" covers both side blocks
        ext = make(self.tmp, "acme")
        with open(os.path.join(ext, "layout.html"), "w") as f:
            f.write('<div class="wrap" data-slot="header"></div><!-- slot: rest -->')
        os.environ["OPENVITA_TEMPLATES"] = self.tmp
        self.assertTrue(self.templates.find("acme")["layout"])
        self.assertIn('<div class="wrap">\n<header class="header">', self.templates.laid_out("", self.CV).replace("\n\n", "\n"))
        self.assertEqual(self.templates.laid_out("", self.CV.replace("acme", "classic")), self.CV.replace("acme", "classic"))

    def test_new_template(self):
        src = make(self.tmp, "acme", css='.x { background: url(template:acme/assets/a.png); }')
        with open(os.path.join(src, "layout.html"), "w") as f:
            f.write('<img src="template:acme/assets/logo.png"><!-- slot: rest -->')
        os.environ["OPENVITA_TEMPLATES"] = self.tmp
        dest = os.path.join(self.tmp, "mine")
        made = self.templates.new("kari-cv", dest, "acme")
        with open(os.path.join(made, "template.json")) as f:
            self.assertEqual(json.load(f)["name"], "kari-cv")
        for f, want in (("cv.css", "template:kari-cv/assets/a.png"), ("layout.html", "template:kari-cv/assets/logo.png")):
            with open(os.path.join(made, f)) as fh:
                self.assertIn(want, fh.read())
        with self.assertRaises(SystemExit):
            self.templates.new("kari-cv", dest, "acme")  # never over an existing folder
        with self.assertRaises(SystemExit):
            self.templates.new("Bad Name", dest)

    def test_check_sample(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("template_check", os.path.join(ROOT, "tools", "template-check.py"))
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        text = check.sample(self.templates.find("classic"), "en")
        for piece in ('<div class="photo">', '<section class="highlight">', '<h2 class="page-title same-page">'):
            self.assertEqual(text.count(piece), 1, piece)
        self.assertEqual([n for n, _ in self.templates.blocks(text.split("<body>")[1].split("</body>")[0]) if n][:4],
                         ["photo", "header", "profile", "sidebar-main"])  # classic has no brand
        want = check.expected(text)
        self.assertIn("Ola Eksempel", want)
        self.assertIn("Highlight", want)


if __name__ == "__main__":
    unittest.main()
