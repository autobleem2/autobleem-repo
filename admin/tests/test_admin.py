"""The admin panel's service over a fake GitHub: who may look and act, the actions and their audit trail, the
time-left estimate, the channels, and the notifier.

    cd admin && python -m pytest -q
"""
import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["AB_ADMIN_NO_APP"] = "1"
from app import main  # noqa: E402
from app.actions import next_tag  # noqa: E402
from app.config import Settings  # noqa: E402
from app.notify import Notifier  # noqa: E402
from app.runs import Runs, median_duration  # noqa: E402


def run(i, status="completed", conclusion="success", start="2026-09-23T10:00:00Z", end="2026-09-23T10:10:00Z",
        workflow=7, branch="develop"):
    return {"id": i, "name": "build", "workflow_id": workflow, "display_title": "t%d" % i, "head_branch": branch,
            "event": "push", "status": status, "conclusion": conclusion, "run_started_at": start,
            "updated_at": end, "html_url": "https://github.com/x/%d" % i, "actor": {"login": "someone"}}


class FakeGitHub:
    def __init__(self):
        self.members = {"alice", "bob"}
        self.managers = {"alice"}
        self.tokens = {"tok-alice": "alice", "tok-bob": "bob", "tok-eve": "eve"}
        self.calls = []
        self.runs = {"autobleem": [run(1, "in_progress", None, end=None), run(2)]}
        self.tags = ["v2.0.0-alpha1", "v2.0.0-alpha2", "nightly"]

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
        if "/actions/runs?per_page" in path:
            return {"workflow_runs": self.runs.get(path.split("/")[3], [])}
        if "/workflows/" in path and "status=success" in path:
            return {"workflow_runs": [run(10, start="2026-09-23T09:00:00Z", end="2026-09-23T09:20:00Z")]}
        if path.endswith("/jobs?per_page=50"):
            return {"jobs": [{"name": "build (psc)", "status": "in_progress", "html_url": "u"}]}
        if path.endswith("/tags?per_page=100"):
            return [{"name": t} for t in self.tags]
        return {}


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "site"
    (repo / "releases").mkdir(parents=True)
    (repo / "nightly").mkdir()
    (repo / "releases" / "unstable.json").write_text(json.dumps(
        {"version": "v2.0.0-alpha2", "prerelease": True, "files": {"psc-fs": {}, "rpi": {}}}))
    (repo / "releases" / "latest.json").write_text(json.dumps({"version": "v2.0.0-alpha2", "prerelease": True}))
    (repo / "nightly" / "latest.json").write_text(json.dumps(
        {"version": "v2.0.0-alpha2-25-g7a37132", "files": {"psc-fs": {}}, "images": {"armhf": {}}}))
    settings = Settings(repo_dir=str(repo), data_dir=str(tmp_path / "data"), repos=["autobleem"])
    gh = FakeGitHub()
    client = TestClient(main.create_app(settings, gh=gh, start_notifier=False))
    return client, gh, settings


def browser(user, act=False):
    h = {"X-Forwarded-User": user}
    if act:
        h["X-AB-Request"] = "1"
    return h


def test_who_may_look(setup):
    client, gh, _ = setup
    assert client.get("/admin/api/status").status_code == 401
    assert client.get("/admin/api/status", headers=browser("eve")).status_code == 403
    assert client.get("/admin/api/status", headers={"Authorization": "Bearer tok-eve"}).status_code == 403
    assert client.get("/admin/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    me = client.get("/admin/api/me", headers=browser("bob")).json()
    assert me == {"login": "bob", "via": "browser", "can_act": False}
    assert client.get("/admin/api/me", headers={"Authorization": "Bearer tok-alice"}).json()["via"] == "api"


def test_who_may_act(setup):
    client, gh, _ = setup
    body = {"platforms": ["psc"]}
    assert client.post("/admin/api/nightly", json=body, headers=browser("bob", True)).status_code == 403
    assert client.post("/admin/api/nightly", json=body, headers=browser("alice")).status_code == 403  # no X-AB
    r = client.post("/admin/api/nightly", json=body, headers=browser("alice", True))
    assert r.status_code == 200
    dispatch = [c for c in gh.calls if c[0] == "POST"][-1]
    assert dispatch[1] == "/repos/autobleem2/autobleem-main/actions/workflows/nightly.yml/dispatches"
    assert dispatch[2]["inputs"]["platforms"] == "psc"
    # a script needs no X-AB-Request
    assert client.post("/admin/api/page", headers={"Authorization": "Bearer tok-alice"}).status_code == 200
    audit = client.get("/admin/api/audit", headers=browser("bob")).json()
    assert [(a["user"], a["via"], a["action"]) for a in audit] == [("alice", "api", "page"),
                                                                     ("alice", "browser", "nightly")]


def test_promote_preview_and_refusals(setup):
    client, gh, _ = setup
    assert client.get("/admin/api/promote/preview?kind=alpha", headers=browser("bob")).json() == {
        "tag": "v2.0.0-alpha3"}
    assert client.get("/admin/api/promote/preview?kind=rc", headers=browser("bob")).json() == {"tag": "v2.0.0-rc1"}
    r = client.post("/admin/api/promote", json={"kind": "alpha", "version": "2.x"}, headers=browser("alice", True))
    assert r.status_code == 400
    r = client.post("/admin/api/promote", json={"kind": "beta"}, headers=browser("alice", True))
    assert r.json()["result"] == "promotion to v2.0.0-beta1 (dry run) started"
    r = client.post("/admin/api/withdraw", json={"kind": "testing", "version": "v2.0.0"},
                    headers=browser("alice", True))
    assert r.status_code == 400  # a stable release is not withdrawn here
    r = client.post("/admin/api/runs/not-ours/5/cancel", headers=browser("alice", True))
    assert r.status_code == 400


def test_status_and_time_left(setup):
    client, gh, _ = setup
    s = client.get("/admin/api/status", headers=browser("bob")).json()
    assert [r["id"] for r in s["active"]] == [1]
    assert s["active"][0]["typical"] == 1200
    assert s["active"][0]["jobs"][0]["name"] == "build (psc)"
    assert [r["id"] for r in s["recent"]] == [2]
    runs = Runs(gh, Settings(repos=["autobleem"]))
    now = datetime(2026, 9, 23, 10, 5, tzinfo=timezone.utc)
    active = runs.status(now=now)["active"][0]
    assert (active["elapsed"], active["left"]) == (300, 900)


def test_median_duration():
    assert median_duration([run(1), run(2, end="2026-09-23T10:30:00Z"), run(3, conclusion="failure")]) == 1200
    assert median_duration([run(1, "in_progress", None)]) is None


def test_channels(setup):
    client, gh, _ = setup
    c = client.get("/admin/api/channels", headers=browser("bob")).json()
    assert c["release"] is None  # latest.json holds a pre-release: there is no release channel yet
    assert c["testing"]["version"] == "v2.0.0-alpha2"
    assert c["nightly"] == {"version": "v2.0.0-alpha2-25-g7a37132", "date": None, "packages": ["psc-fs"],
                            "images": ["armhf"]}


def test_next_tag():
    assert next_tag(["v2.0.0-alpha2"], "alpha") == "v2.0.0-alpha3"
    assert next_tag(["v2.0.0-alpha2", "v2.0.0"], "alpha", "2.1.0") == "v2.1.0-alpha1"
    with pytest.raises(ValueError):
        next_tag(["v2.0.0"], "beta")


def test_notifier_reports_a_finished_run_once(tmp_path):
    gh = FakeGitHub()
    settings = Settings(data_dir=str(tmp_path), repos=["autobleem"], telegram_token="t", telegram_chat="c")
    sent = []
    n = Notifier(Runs(gh, settings), settings, send=sent.append)
    n.tick()  # run 1 is running, run 2 finished before we looked: nothing to say
    assert sent == []
    gh.runs["autobleem"][0] = run(1, "completed", "failure")
    n.tick()
    n.tick()
    assert len(sent) == 1 and "autobleem" in sent[0] and "failure" in sent[0]
    again = Notifier(Runs(gh, settings), settings, send=sent.append)  # a restart remembers
    again.seen_active.add(("autobleem", 1))
    again.tick()
    assert len(sent) == 1


def test_notifier_disk_alert_once_and_recovery(tmp_path, monkeypatch):
    from app import notify
    settings = Settings(data_dir=str(tmp_path), repos=["autobleem"], telegram_token="t", telegram_chat="c",
                        low_disk_gb=10)
    sent = []
    n = Notifier(Runs(FakeGitHub(), settings), settings, send=sent.append)
    for free_gb, count in ((20, 0), (9, 1), (5, 1), (11, 1), (13, 2), (8, 3)):
        monkeypatch.setattr(notify, "disk_free", lambda path, f=free_gb: f * 1e9)
        n.check_disk()
        assert len(sent) == count, (free_gb, sent)
    assert "9.0 GB free" in sent[0] and "again" in sent[1]
