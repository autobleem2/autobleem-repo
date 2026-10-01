"""The roadmap tab's data (R27, autobleem-main docs/admin-roadmap-plan.md): todo.md, roadmap.md and status.json,
read from autobleem-main's develop through the App's contents API and cached for a minute. The panel owns none
of it - the Program Manager writes status.json, the teams keep todo.md.
"""
import base64
import json
import re
from datetime import datetime, timedelta, timezone

from .github import GitHubError

MAIN_REPO = "autobleem-main"
BRANCH = "develop"
TTL = 60
# status.json is written by hand (the Program Manager's status pushes were retired); past this age it is not "now"
STATUS_MAX_AGE = timedelta(hours=24)


def _parse_when(text):
    """An ISO time with an offset as an aware datetime, or None when it is missing or unreadable."""
    try:
        when = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
# a how-to page for something the owner does himself (decisions.md, "Owner tasks come with a how-to"):
# autobleem-main/howto/<name>.html, named in status.json as "howto/<name>.html"
HOWTO = re.compile(r"^howto/([a-z0-9][a-z0-9-]{0,63})\.html$")


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

    def teams(self, now=None):
        """status.json as the page wants it; {"status": None, ...} when there is none yet, it is unreadable, or
        it is older than `STATUS_MAX_AGE` (nothing writes it any more - old teams shown as current would
        mislead; the reason says so and the page prints it)."""
        raw = self.text("status.json")
        if raw is None:
            return {"status": None, "reason": "no status.json yet"}
        try:
            data = json.loads(raw)
        except ValueError as e:
            return {"status": None, "reason": "status.json is not valid JSON: %s" % e}
        if not isinstance(data, dict) or data.get("schema") != 1:
            return {"status": None, "reason": "status.json has an unknown schema"}
        written = _parse_when(data.get("written_at"))
        now = now or datetime.now(timezone.utc)
        if written is not None and now - written > STATUS_MAX_AGE:
            return {"status": None, "written_at": data.get("written_at", ""),
                    "reason": "no source: status.json was last written %s and nothing updates it any more"
                              % str(data.get("written_at", ""))[:10]}
        return {"status": {
            "written_at": data.get("written_at", ""),
            "written_by": data.get("written_by", ""),
            "usage": data.get("usage") or {},
            "teams": [_team(t) for t in data.get("teams") or [] if isinstance(t, dict)],
            "needs_owner": [_need(i) for i in data.get("needs_owner") or [] if isinstance(i, dict)],
        }}

    def howto(self, name):
        """The how-to page `howto/<name>.html` as HTML text, or None (a bad name or no such page)."""
        if not HOWTO.match("howto/%s.html" % name):
            return None
        return self.text("howto/%s.html" % name)

    def roadmap(self):
        """The parsed todo.md rows and roadmap.md milestones (the parser is app/roadmap.py, step 1)."""
        from .roadmap import parse_milestones, parse_todo
        todo, plan = self.text("docs/todo.md"), self.text("docs/roadmap.md")
        return {"rows": parse_todo(todo or ""), "milestones": parse_milestones(plan or "")}


def _item(d, keys):
    return {k: str(d.get(k, "")) for k in keys}


def _need(d):
    """An owner-queue entry; `howto` is the page's name (what /admin/api/howto/<name> serves) or ""."""
    m = HOWTO.match(str(d.get("howto", "")))
    return dict(_item(d, ("id", "kind", "what")), howto=m.group(1) if m else "")


def _team(t):
    return {"name": str(t.get("name", "")), "team": str(t.get("team", "")),
            "state": t.get("state") if t.get("state") in ("working", "waiting", "asleep") else "unknown",
            "items": [_item(i, ("id", "what")) for i in t.get("items") or [] if isinstance(i, dict)],
            "note": str(t.get("note", ""))}
