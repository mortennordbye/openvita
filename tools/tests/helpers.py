"""Shared set-up for the tool tests: a temporary local/ folder and a quiet, isolated git."""
import importlib
import os
import shutil
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
EXAMPLE = os.path.join(ROOT, "openself", "example")
sys.path.insert(0, TOOLS)

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class LocalDir:
    """Mixin: self.tmp is local/, and the tool modules are reloaded to see it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = dict(os.environ)
        os.environ.update(GIT_ENV, OPENVITA_LOCAL=self.tmp)
        os.environ.pop("OPENVITA_TEMPLATES", None)
        import profiles, templates, draft  # noqa: E401
        self.profiles = importlib.reload(profiles)
        self.templates = importlib.reload(templates)
        self.draft = importlib.reload(draft)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def person(self, c="ola", profile=None):
        os.makedirs(os.path.join(self.tmp, c), exist_ok=True)
        if profile:
            self.profiles.connect(c, profile)
        return os.path.join(self.tmp, c)
