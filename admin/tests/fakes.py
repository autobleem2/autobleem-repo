"""The fake GitHub and the run builder the admin tests (and tools/dev_server.py) share - no pytest needed."""
import base64
import os

os.environ.setdefault("AB_ADMIN_NO_APP", "1")
from app.github import GitHubError  # noqa: E402


def run(i, status="completed", conclusion="success", start="2026-09-23T10:00:00Z", end="2026-09-23T10:10:00Z",
        workflow=7, branch="develop", created="2026-09-23T09:59:00Z"):
    return {"id": i, "name": "build", "workflow_id": workflow, "display_title": "t%d" % i, "head_branch": branch,
            "event": "push", "status": status, "conclusion": conclusion, "created_at": created,
            "run_started_at": start, "updated_at": end, "html_url": "https://github.com/x/%d" % i,
            "actor": {"login": "someone"}}


DEFAULT_JOBS = [{"name": "build (psc)", "status": "in_progress", "html_url": "u", "runner_name": "runner-1",
                 "labels": ["self-hosted", "psc"],
                 "steps": [{"number": 1, "name": "Checkout", "status": "completed", "conclusion": "success",
                            "started_at": "2026-09-23T10:00:00Z", "completed_at": "2026-09-23T10:00:05Z"},
                           {"number": 2, "name": "Build", "status": "in_progress", "conclusion": None,
                            "started_at": "2026-09-23T10:00:05Z", "completed_at": None}]}]


class FakeGitHub:
    def __init__(self):
        self.members = {"alice", "bob"}
        self.managers = {"alice"}
        self.tokens = {"tok-alice": "alice", "tok-bob": "bob", "tok-eve": "eve"}
        self.calls = []
        self.runs = {"autobleem": [run(1, "in_progress", None, end=None), run(2)]}
        self.jobs = {1: DEFAULT_JOBS}
        self.tags = ["v2.0.0-alpha1", "v2.0.0-alpha2", "nightly"]
        self.runners = [{"id": 1, "name": "runner-1", "status": "online", "busy": True,
                         "labels": [{"name": "self-hosted"}, {"name": "psc"}]},
                        {"id": 2, "name": "runner-2", "status": "offline", "busy": False, "labels": []}]
        self.runners_status = 200
        self.contents = {}  # path (under autobleem-main's develop) -> text, for the roadmap/bugs contents API
        self.events = {}    # repo -> its events (push events), for the Preview box's recent branches

    def cached(self, key, ttl, fn):
        return fn()

    def login_of_token(self, token):
        return self.tokens.get(token)

    def is_member(self, login):
        return login in self.members

    def is_release_manager(self, login):
        return login in self.managers

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "/contents/" in path:
            name = path.split("/contents/", 1)[1].split("?", 1)[0]
            if name not in self.contents:
                raise GitHubError(404, "Not Found")
            return {"content": base64.b64encode(self.contents[name].encode("utf-8")).decode("ascii")}
        if "/actions/runners?per_page" in path:
            if self.runners_status != 200:
                raise GitHubError(self.runners_status, "no access")
            return {"runners": self.runners}
        if "/actions/runs?per_page" in path:
            return {"workflow_runs": self.runs.get(path.split("/")[3], [])}
        if "/workflows/" in path and "status=success" in path:
            return {"workflow_runs": [run(10, start="2026-09-23T09:00:00Z", end="2026-09-23T09:20:00Z")]}
        if "/jobs?per_page=50" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": self.jobs.get(run_id, [])}
        if "/events?per_page" in path:
            return self.events.get(path.split("/")[3], [])
        if path.endswith("/tags?per_page=100"):
            return [{"name": t} for t in self.tags]
        return {}
