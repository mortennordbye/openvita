import json
import os
import shutil
import subprocess
import unittest

from helpers import EXAMPLE, LocalDir


class Profiles(LocalDir, unittest.TestCase):
    def test_profile_dir_default_and_config(self):
        d = self.person("kari")
        self.assertEqual(self.profiles.profile_dir("kari"), os.path.join(d, "profile"))
        for value, expected in (("elsewhere/p", os.path.join(d, "elsewhere", "p")),
                                ("/abs/p", "/abs/p"), ("~/p", os.path.expanduser("~/p"))):
            with open(os.path.join(d, "openvita.json"), "w") as f:
                json.dump({"profile": value}, f)
            self.assertEqual(self.profiles.profile_dir("kari"), expected)
        with self.assertRaises(ValueError):
            self.profiles.profile_dir("../x")
        with self.assertRaises(ValueError):
            self.profiles.profile_dir("customers")

    def test_init_ignores_profile_in_person_repo(self):
        d = self.person("kari")
        subprocess.run(["git", "init", "-q", d], check=True)
        p = self.profiles.init("kari")
        self.assertTrue(self.profiles.exists("kari"))
        self.assertTrue(os.path.isdir(os.path.join(p, ".git")))
        self.profiles.init("kari")  # again: no second ignore line
        with open(os.path.join(d, ".gitignore")) as f:
            self.assertEqual(f.read(), "/profile/\n")
        status = subprocess.run(["git", "-C", d, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertNotIn("profile", status)

    def test_connect_profile_and_home(self):
        self.person("ola", EXAMPLE)
        self.assertEqual(self.profiles.profile_dir("ola"), EXAMPLE)
        self.assertEqual(self.profiles.config("ola")["profile"], EXAMPLE)  # local/ is outside the repo here: absolute
        self.assertEqual(self.profiles.language("ola"), "nb")  # the example's first language

        home = os.path.join(self.tmp, "home")  # an OpenSelf home: the profile is in profile/
        shutil.copytree(EXAMPLE, os.path.join(home, "profile"))
        self.profiles.connect("ola", home)
        self.assertEqual(self.profiles.profile_dir("ola"), os.path.join(home, "profile"))

        self.profiles.set_config("ola", language="en")
        self.assertEqual(self.profiles.language("ola"), "en")
        with self.assertRaises(SystemExit):
            self.profiles.connect("ola", self.tmp)  # no openself.json anywhere


if __name__ == "__main__":
    unittest.main()
