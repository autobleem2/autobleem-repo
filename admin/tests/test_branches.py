"""The Preview box's recent branches: push events across the repositories, newest first.

    cd admin && python -m pytest -q
"""
from app.branches import Branches
from app.config import Settings
from app.github import GitHubError


def push(branch, at):
    return {"type": "PushEvent", "created_at": at, "payload": {"ref": "refs/heads/" + branch}}


class Fake:
    def __init__(self, events):
        self.events = events

    def cached(self, key, ttl, fn):
        return fn()

    def call(self, method, path, body=None):
        repo = path.split("/")[3]
        if repo not in self.events:
            raise GitHubError(404, "Not Found")
        return self.events[repo]


def test_newest_feature_branch_first_across_repos():
    gh = Fake({
        "core": [push("feature/a", "2026-10-02T00:10:00Z"), push("develop", "2026-10-02T00:30:00Z"),
                 {"type": "CreateEvent", "created_at": "2026-10-02T00:40:00Z", "payload": {"ref": "feature/x"}}],
        "launcher": [push("feature/b", "2026-10-02T00:20:00Z"), push("feature/a", "2026-10-02T00:05:00Z"),
                     push("dependabot/npm/x", "2026-10-02T00:50:00Z")],
    })
    got = Branches(gh, Settings(repos=["core", "launcher", "gone"])).recent()
    assert [b["branch"] for b in got] == ["feature/b", "feature/a"]
    assert got[1] == {"branch": "feature/a", "at": "2026-10-02T00:10:00Z", "repos": ["core", "launcher"]}


def test_no_events_no_branches():
    assert Branches(Fake({}), Settings(repos=["core"])).recent() == []
