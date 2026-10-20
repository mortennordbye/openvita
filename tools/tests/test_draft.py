import os
import re
import shutil
import unittest

from helpers import EXAMPLE, LocalDir


class Draft(LocalDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.prof = os.path.join(self.tmp, "profile-copy")
        shutil.copytree(EXAMPLE, self.prof)
        self.person("ola", self.prof)

    def cv(self, **kw):
        with open(self.draft.write("ola", **kw), encoding="utf-8") as f:
            return f.read()

    def test_customers_hidden(self):
        self.profiles.set_config("ola", customers="hidden")
        html = self.cv()
        self.assertNotIn("Statens testverk", html)  # public in the profile, hidden by choice
        self.assertIn("en statlig etat", html)  # its alias
        self.assertIn("Statens testverk", self.cv(customers="named", force=True))  # the flag wins over the config

    def test_customers_hidden_warns_about_names_in_text(self):
        path = os.path.join(self.prof, "assignments", "2023-09-statens-testverk-plattformingenior.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("Ny intern utviklerplattform", "Ny intern utviklerplattform for Statens testverk"))
        self.assertEqual(self.draft.warn_names("ola", "<p>for Statens testverk</p>", "hidden"), ["Statens testverk"])
        self.assertEqual(self.draft.warn_names("ola", "<p>for Statens testverk</p>", "named"), [])

    def test_respects_the_profile_rules(self):
        html = self.cv()
        self.assertIn('href="template:classic/cv.css"', html)
        self.assertIn("Ola Eksempel", html)
        self.assertIn('data-entry="2023-09-statens-testverk-plattformingenior"', html)
        self.assertIn("Statens testverk", html)  # customer_public: public
        # omit flag: the facts stay, the text and the on-call rota go, the wish is left as a comment
        self.assertIn("Nordlys Drift AS", html)
        self.assertNotIn("Vakt annenhver", html)
        self.assertIn("<!-- omit: Ikke nevn vaktordningen i CV-er. -->", html)
        # the private reference section, the owner's words and the flags never go in
        self.assertNotIn("Referanse", html)
        with open(os.path.join(self.prof, "assignments", "2023-09-statens-testverk-plattformingenior.md"), encoding="utf-8") as f:
            ref = f.read()
        private = ref.split("## Referanse (privat)", 1)[1].split("##", 1)[0].strip().splitlines()[0]
        self.assertNotIn(private.strip("- "), html)
        self.assertNotIn("Brukerens ord", html)
        self.assertNotIn("Terraform-koden før noen andre", html)
        self.assertNotIn("⚑", html)
        # anonymised customer: only the alias
        self.assertNotIn("Vestkraft", html)
        self.assertIn("et regionalt kraftselskap", html)
        # removed entries never
        self.assertNotIn("2021-03-fjordsky-pilot", html)
        # Norwegian profile: Norwegian headings and months
        self.assertIn("Erfaring", html)
        self.assertIn("mar 2021 – nå", html)

    def test_nda_customer_left_out(self):
        path = os.path.join(self.prof, "assignments", "2021-04-vestkraft-skymigrering.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("customer_public: anonymised", "customer_public: nda"))
        html = self.cv()
        self.assertNotIn("2021-04-vestkraft-skymigrering", html)
        self.assertNotIn("kraftselskap", html)

    def test_english_and_overwrite_rules(self):
        html = self.cv(lang="en")
        self.assertIn("Experience", html)
        self.assertIn("Mar 2021 – present", html)
        self.cv(lang="en")  # unchanged since the last draft: replaced without asking
        path = self.draft.target("ola")
        with open(path, "a", encoding="utf-8") as f:
            f.write("<!-- edited by hand -->\n")
        with self.assertRaises(SystemExit):
            self.cv()
        self.assertIn("Erfaring", self.cv(force=True))

    def test_template_kept_and_brand(self):
        self.cv(template="sidebar")
        self.assertIn("template:sidebar/cv.css", self.cv())  # a redraft keeps the CV's template
        html = self.cv(template="classic")
        self.assertIn("<!-- brand --><!-- /brand -->", html)
        self.assertTrue(re.search(r"<!-- openvita draft [0-9a-f]{12} -->", html))


    def test_switch(self):
        import json
        company = os.path.join(self.tmp, "acme")
        os.makedirs(company)
        with open(os.path.join(company, "template.json"), "w") as f:
            json.dump({"brand": {"name": "Acme AS", "email": "{first}.{last}@acme.example", "address": "Main St 1"}}, f)
        with open(os.path.join(company, "cv.css"), "w") as f:
            f.write("body {}")
        self.profiles.set_config("ola", templates=[company])
        path = self.draft.write("ola", lang="en")
        self.draft.switch("ola", path, "acme")  # untouched draft: drafted again, contact follows the brand
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("ola.eksempel@acme.example", html)
        self.assertIn("Experience", html)  # the language stays
        with open(path, "a", encoding="utf-8") as f:
            f.write("<!-- edited -->\n")
        self.draft.switch("ola", path, "classic")  # edited: only the look changes
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("template:classic/cv.css", html)
        self.assertIn("ola.eksempel@acme.example", html)
        self.assertIn("<!-- brand --><!-- /brand -->", html)


    def test_own_markup_templates(self):
        import json
        family = os.path.join(self.tmp, "family")
        for name in ("old", "old-light"):
            os.makedirs(os.path.join(family, name))
            with open(os.path.join(family, name, "template.json"), "w") as f:
                json.dump({"label": name, "markup": "hand-2025"}, f)
            with open(os.path.join(family, name, "cv.css"), "w") as f:
                f.write("body {}")
        self.profiles.set_config("ola", templates=[family])
        with self.assertRaises(SystemExit) as e:
            self.draft.write("ola", template="old")  # a draft is openvita markup only
        self.assertIn("its own markup", str(e.exception))
        path = self.draft.target("ola", app="2026-10-x")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write('<link rel="stylesheet" href="template:old/cv.css"><img src="template:old/assets/logo.png">\n')
        self.draft.switch("ola", path, "old-light")  # same family: fine, assets follow
        with open(path, encoding="utf-8") as f:
            self.assertIn("template:old-light/assets/logo.png", f.read())
        with self.assertRaises(SystemExit) as e:
            self.draft.switch("ola", path, "classic")  # other markup: refused
        self.assertIn("same markup", str(e.exception))
        self.assertEqual(self.templates.find("old", "ola")["markup"], "hand-2025")
        self.assertEqual(self.templates.find("classic", "ola")["markup"], "openvita")


if __name__ == "__main__":
    unittest.main()
