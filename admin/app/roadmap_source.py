"""The roadmap tab's data (R27, autobleem-main docs/admin-roadmap-plan.md): todo.md, roadmap.md and status.json,
read from autobleem-main's develop through the App's contents API and cached for a minute. The panel owns none
of it - the Program Manager writes status.json, the teams keep todo.md.
"""
import base64
import json

from .github import GitHubError

MAIN_REPO = "autobleem-main"
BRANCH = "develop"
TTL = 60


class RoadmapSource:
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

    def teams(self):
        """status.json as the page wants it; {"status": None, ...} when there is none yet or it is unreadable."""
        raw = self.text("status.json")
        if raw is None:
            return {"status": None, "reason": "no status.json yet"}
        try:
            data = json.loads(raw)
        except ValueError as e:
            return {"status": None, "reason": "status.json is not valid JSON: %s" % e}
        if not isinstance(data, dict) or data.get("schema") != 1:
            return {"status": None, "reason": "status.json has an unknown schema"}
        return {"status": {
            "written_at": data.get("written_at", ""),
            "written_by": data.get("written_by", ""),
            "usage": data.get("usage") or {},
            "teams": [_team(t) for t in data.get("teams") or [] if isinstance(t, dict)],
            "needs_owner": [_item(i, ("id", "kind", "what")) for i in data.get("needs_owner") or []
                            if isinstance(i, dict)],
        }}

    def roadmap(self):
        """The parsed todo.md rows and roadmap.md milestones (the parser is app/roadmap.py, step 1)."""
        from .roadmap import parse_milestones, parse_todo
        todo, plan = self.text("docs/todo.md"), self.text("docs/roadmap.md")
        return {"rows": parse_todo(todo or ""), "milestones": parse_milestones(plan or "")}


def _item(d, keys):
    return {k: str(d.get(k, "")) for k in keys}


def _team(t):
    return {"name": str(t.get("name", "")), "team": str(t.get("team", "")),
            "state": t.get("state") if t.get("state") in ("working", "waiting", "asleep") else "unknown",
            "items": [_item(i, ("id", "what")) for i in t.get("items") or [] if isinstance(i, dict)],
            "note": str(t.get("note", ""))}
