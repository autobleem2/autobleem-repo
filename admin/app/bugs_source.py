"""The Bugs tab's data (PLATFORM-9 part 2): `docs/bugs.md`, read from autobleem-main's develop through the
App's contents API and cached for a minute - the same source mode and the same caching `roadmap_source.py`
uses for the roadmap tab. The panel owns none of it: `docs/bugs.md`'s own header (PLATFORM-9 part 1) says
who records a bug and when; this only reads and parses what is there.
"""
import base64

from .bugs import parse_bugs
from .github import GitHubError

MAIN_REPO = "autobleem-main"
BRANCH = "develop"
TTL = 60


class BugsSource:
    def __init__(self, gh, settings):
        self.gh, self.settings = gh, settings

    def text(self, path):
        """A file of autobleem-main's develop as text, or None when it is not there."""
        def ask():
            try:
                reply = self.gh.call("GET", "/repos/%s/%s/contents/%s?ref=%s"
                                     % (self.settings.org, MAIN_REPO, path, BRANCH))
            except GitHubError as e:
                if e.status == 404:
                    return None
                raise
            return base64.b64decode(reply.get("content", "")).decode("utf-8")
        return self.gh.cached("main:" + path, TTL, ask)

    def bugs(self):
        """The parsed `docs/bugs.md` rows (the parser is `app/bugs.py`'s `parse_bugs`)."""
        return parse_bugs(self.text("docs/bugs.md") or "")
