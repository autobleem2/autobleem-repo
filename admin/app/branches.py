"""The branches pushed most recently across the panel's repositories - the Preview box starts with the newest one.

One events call per repository (`/repos/<org>/<repo>/events`, the push events of the last days), cached for two
minutes. develop/master/main and bot branches are left out: a preview builds a feature branch.
"""
from .github import GitHubError

TTL = 120
KEEP = 10
SKIP = ("develop", "master", "main")


class Branches:
    def __init__(self, gh, settings):
        self.gh, self.settings = gh, settings

    def events(self, repo):
        path = "/repos/%s/%s/events?per_page=50" % (self.settings.org, repo)
        return self.gh.cached("events:" + repo, TTL, lambda: self.gh.call("GET", path))

    def recent(self):
        """[{branch, at, repos}], newest push first; a repository the App cannot read is skipped."""
        seen = {}
        for repo in self.settings.repos:
            try:
                events = self.events(repo)
            except GitHubError:
                continue
            for e in events if isinstance(events, list) else []:
                ref = ((e or {}).get("payload") or {}).get("ref") or ""
                if e.get("type") != "PushEvent" or not ref.startswith("refs/heads/"):
                    continue
                branch = ref[len("refs/heads/"):]
                if branch in SKIP or branch.startswith("dependabot/"):
                    continue
                at = str(e.get("created_at") or "")
                b = seen.setdefault(branch, {"branch": branch, "at": at, "repos": []})
                if repo not in b["repos"]:
                    b["repos"].append(repo)
                b["at"] = max(b["at"], at)
        return sorted(seen.values(), key=lambda b: b["at"], reverse=True)[:KEEP]
