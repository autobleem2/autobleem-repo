"""R27: status.json and the files the roadmap tab reads, over a fake contents API.

    cd admin && python -m pytest -q
"""
import base64
import json

from app.config import Settings
from app.github import GitHubError
from app.roadmap_source import RoadmapSource


class FakeContents:
    def __init__(self, files):
        self.files, self.paths = files, []

    def cached(self, key, ttl, fn):
        return fn()

    def call(self, method, path, body=None):
        self.paths.append(path)
        name = path.split("/contents/", 1)[1].split("?", 1)[0]
        if name not in self.files:
            raise GitHubError(404, "Not Found")
        return {"content": base64.b64encode(self.files[name].encode("utf-8")).decode("ascii")}


def source(files):
    return RoadmapSource(FakeContents(files), Settings())


STATUS = {
    "schema": 1, "written_at": "2026-09-27T05:02:00+01:00", "written_by": "Eleanor Voss - Program Manager",
    "usage": {"five_hour_percent": 93},
    "teams": [{"name": "Victor Lane", "team": "infrastructure", "state": "working",
               "items": [{"id": "R27", "what": "the roadmap tab"}], "note": "", "extra": 1},
              {"name": "Wren", "team": "task force", "state": "dancing", "items": []}, "not a team"],
    "needs_owner": [{"id": "C11-B", "kind": "device test", "what": "pad swap"}],
    "unknown_key": True,
}


def test_reads_develop_of_autobleem_main():
    s = source({"status.json": json.dumps(STATUS)})
    s.teams()
    assert s.gh.paths == ["/repos/autobleem2/autobleem-main/contents/status.json?ref=develop"]


def test_status_is_passed_on_cleaned():
    got = source({"status.json": json.dumps(STATUS)}).teams()["status"]
    assert got["usage"] == {"five_hour_percent": 93}
    assert got["teams"][0] == {"name": "Victor Lane", "team": "infrastructure", "state": "working",
                               "items": [{"id": "R27", "what": "the roadmap tab"}], "note": ""}
    assert got["teams"][1]["state"] == "unknown"
    assert len(got["teams"]) == 2
    assert got["needs_owner"] == [{"id": "C11-B", "kind": "device test", "what": "pad swap", "howto": ""}]


def test_no_status_yet():
    assert source({}).teams() == {"status": None, "reason": "no status.json yet"}


def test_bad_json_and_unknown_schema():
    assert source({"status.json": "{"}).teams()["status"] is None
    assert source({"status.json": json.dumps({"schema": 2})}).teams()["reason"] == "status.json has an unknown schema"


def test_a_howto_page_is_named_and_served():
    status = dict(STATUS, needs_owner=[
        {"id": "R26 login", "kind": "action", "what": "log in", "howto": "howto/claude-login.html"},
        {"id": "X", "kind": "action", "what": "x", "howto": "../secrets.html"},
        {"id": "Y", "kind": "action", "what": "y", "howto": "howto/Bad Name.html"}])
    s = source({"status.json": json.dumps(status), "howto/claude-login.html": "<h1>Logowanie</h1>"})
    assert [n["howto"] for n in s.teams()["status"]["needs_owner"]] == ["claude-login", "", ""]
    assert s.howto("claude-login") == "<h1>Logowanie</h1>"
    assert s.gh.paths[-1] == "/repos/autobleem2/autobleem-main/contents/howto/claude-login.html?ref=develop"


def test_a_howto_name_never_leaves_the_folder():
    s = source({"howto/x.html": "x"})
    assert s.howto("missing") is None
    for bad in ("../status", "a/b", "X", "", "a.html"):
        assert s.howto(bad) is None
    assert all("/contents/howto/" in p for p in s.gh.paths)
