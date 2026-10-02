"""The roadmap tab's data (R27, autobleem-main docs/admin-roadmap-plan.md): todo.md and roadmap.md, read from
autobleem-main's develop through the App's contents API and cached for a minute, and the Teams tab's private
teams.json, a file pushed to the server and mounted read-only. The panel owns none of it.
"""
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone

from .github import GitHubError

MAIN_REPO = "autobleem-main"
BRANCH = "develop"
TTL = 60
# teams.json is pushed by the company's tool; past this age it is not "now"
TEAMS_MAX_AGE = timedelta(minutes=60)


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
        """The teams file (`settings.teams_file`, a private teams.json the company pushes to the server) as the
        page wants it; {"status": None, "reason": ...} when the file is missing, unreadable or older than
        `TEAMS_MAX_AGE` (a stale picture shown as "now" would mislead; the page prints the reason)."""
        path = self.settings.teams_file
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {"status": None, "reason": "no source: %s is missing" % os.path.basename(path)}
        except (OSError, ValueError) as e:
            return {"status": None, "reason": "no source: %s is not readable: %s" % (os.path.basename(path), e)}
        written = _parse_when(data.get("generated_at")) if isinstance(data, dict) else None
        if written is None:
            return {"status": None, "reason": "no source: %s has no generated_at" % os.path.basename(path)}
        now = now or datetime.now(timezone.utc)
        if now - written > TEAMS_MAX_AGE:
            return {"status": None, "written_at": data["generated_at"],
                    "reason": "no source: %s was last written %s (older than %d min)"
                              % (os.path.basename(path), str(data["generated_at"])[:16], TEAMS_MAX_AGE.seconds // 60)}
        flights = {c.get("lead"): c for c in data.get("contractors") or [] if isinstance(c, dict)}
        return {"status": {
            "written_at": data["generated_at"],
            "mode": str(data.get("mode") or "full"),
            "leads_note": str(data.get("leads_note") or ""),
            "budget": _budget(data.get("budget")),
            "teams": [_session(s, flights.get(s.get("name"))) for s in data.get("sessions") or []
                      if isinstance(s, dict)],
            # sessions waiting for the owner: plain ids (the old feed) or {id, what}
            "needs_owner": [{"id": str(i.get("id", "")) if isinstance(i, dict) else str(i), "kind": "session",
                             "what": str(i.get("what", "")) if isinstance(i, dict) else "", "howto": ""}
                            for i in data.get("waiting_on_owner") or []],
            # the PM's open questions for the owner (owner-questions.md rows nobody has answered yet)
            "questions": [_item(q, ("added", "from", "question", "options"))
                          for q in data.get("owner_questions") or [] if isinstance(q, dict)],
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


def _session(s, flight):
    """One teams.json session as a row: its in-flight slots (else its current task) and what waits in its queue."""
    items = [_item(i, ("id", "desc")) for i in (flight or {}).get("in_flight") or [] if isinstance(i, dict)]
    items = [{"id": i["id"], "what": i["desc"]} for i in items]
    if not items and s.get("task_id"):
        items = [{"id": str(s["task_id"]), "what": str(s.get("task", ""))}]
    queued = [str(q) for q in (flight or {}).get("queued") or []]
    return {"name": str(s.get("name", "")), "team": " · ".join(x for x in (str(s.get("role", "")), str(s.get("model", ""))) if x),
            "state": str(s.get("state", "")) or "unknown", "items": items,
            "note": ("queued: " + ", ".join(queued)) if queued else ("" if items else str(s.get("task", "")))}


def _budget(b):
    """The budget line as numbers or None, so the page prints only what is known."""
    b = b if isinstance(b, dict) else {}
    return {"h5_pct": b.get("h5_pct"), "week_pct": b.get("week_pct"), "pace_pct_per_h": b.get("pace_pct_per_h"),
            "stop_day": b.get("stop_day")}
