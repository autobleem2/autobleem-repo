"""The Teams tab's feed: a private teams.json, fresh, stale, missing or broken.

    cd admin && python -m pytest -q
"""
import json
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.roadmap_source import RoadmapSource

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)

FEED = {
    "generated_at": "2026-10-01T13:50:00+00:00",
    "sessions": [
        {"name": "Lead A", "role": "Lead Software", "model": "model-x", "task_id": "TASK-1",
         "task": "first task", "state": "working"},
        {"name": "Lead B", "role": "Lead QA", "model": "model-y", "task_id": "", "task": "", "state": "idle"},
    ],
    "contractors": [
        {"lead": "Lead A", "max_slots": 2, "queued": ["TASK-9"],
         "in_flight": [{"id": "TASK-1", "desc": "first task", "worker": ""},
                       {"id": "TASK-2", "desc": "second task", "worker": ""}]},
        {"lead": "Lead B", "max_slots": 1, "in_flight": [], "queued": []},
    ],
    "budget": {"h5_pct": 5, "week_pct": 46, "pace_pct_per_h": 0.7, "stop_day": "2026-10-04"},
    "waiting_on_owner": ["TASK-7"],
}


def source(tmp_path, feed=None, raw=None):
    path = tmp_path / "teams.json"
    if feed is not None:
        path.write_text(json.dumps(feed), encoding="utf-8")
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    return RoadmapSource(None, Settings(teams_file=str(path)))


def test_a_fresh_feed_is_passed_on(tmp_path):
    got = source(tmp_path, FEED).teams(NOW)["status"]
    assert got["written_at"] == "2026-10-01T13:50:00+00:00"
    assert {k: got["budget"][k] for k in FEED["budget"]} == FEED["budget"]
    assert got["budget"]["series"] == []
    a, b = got["teams"]
    assert (a["name"], a["team"], a["state"]) == ("Lead A", "Lead Software · model-x", "working")
    assert [i["id"] for i in a["items"]] == ["TASK-1", "TASK-2"]
    assert a["note"] == "queued: TASK-9"
    assert (b["state"], b["items"], b["note"]) == ("idle", [], "")
    assert got["needs_owner"] == [{"id": "TASK-7", "kind": "session", "what": "", "howto": "", "blocks": "", "since": ""}]
    assert got["questions"] == []


def test_sessions_and_open_questions_for_the_owner(tmp_path):
    feed = dict(FEED, waiting_on_owner=[{"id": "PSC-TEST", "what": "the game on the console",
                                         "blocks": "the merge waits", "since": "2026-10-01T13:00:00+00:00"}],
                owner_questions=[{"added": "Fri 02.10 01:40", "from": "PM", "question": "BLOCKS X: which way?",
                                  "options": "A / B", "blocking": True}])
    got = source(tmp_path, feed).teams(NOW)["status"]
    assert got["needs_owner"] == [{"id": "PSC-TEST", "kind": "session", "what": "the game on the console",
                                   "howto": "", "blocks": "the merge waits", "since": "2026-10-01T13:00:00+00:00"}]
    assert got["questions"] == [{"added": "Fri 02.10 01:40", "from": "PM", "question": "BLOCKS X: which way?",
                                 "options": "A / B", "blocking": True}]


def test_a_session_without_slots_shows_its_task(tmp_path):
    feed = dict(FEED, contractors=[])
    a = source(tmp_path, feed).teams(NOW)["status"]["teams"][0]
    assert a["items"] == [{"id": "TASK-1", "what": "first task", "worker": "", "kind": "", "since": ""}]


def test_a_contractor_line_carries_its_worker_kind_and_start(tmp_path):
    feed = dict(FEED, contractors=[{"lead": "Lead A", "max_slots": 2, "queued": [], "in_flight": [
        {"id": "TASK-1", "desc": "first task", "worker": "Dev One", "kind": "tester",
         "since": "2026-10-01T13:20:00+00:00"}]}])
    a = source(tmp_path, feed).teams(NOW)["status"]["teams"][0]
    assert a["items"] == [{"id": "TASK-1", "what": "first task", "worker": "Dev One", "kind": "tester",
                           "since": "2026-10-01T13:20:00+00:00"}]


def test_a_crunch_contractor_hangs_under_its_hirer(tmp_path):
    feed = dict(FEED, contractors=[], sessions=[
        {"name": "PM", "role": "Program Manager", "model": "m", "task_id": "", "task": "hub", "state": "working"},
        {"name": "Dev One", "role": "developer", "model": "", "task_id": "TASK-3", "task": "third",
         "state": "working", "under": "PM", "kind": "developer", "since": "2026-10-01T13:30:00+00:00"}])
    pm, dev = source(tmp_path, feed).teams(NOW)["status"]["teams"]
    assert (pm["under"], dev["under"], dev["kind"], dev["team"]) == ("", "PM", "developer", "developer")
    assert dev["items"][0]["since"] == "2026-10-01T13:30:00+00:00"


def test_a_stale_feed_is_no_source(tmp_path):
    s = source(tmp_path, FEED)
    got = s.teams(NOW + timedelta(minutes=51))  # 61 minutes old
    assert got["status"] is None
    assert got["reason"].startswith("no source: teams.json was last written 2026-10-01T13:50")
    assert s.teams(NOW + timedelta(minutes=50))["status"] is not None  # 60 minutes: still fresh


def test_a_missing_feed_is_no_source(tmp_path):
    assert source(tmp_path).teams(NOW) == {"status": None, "reason": "no source: teams.json is missing"}


def test_an_unreadable_feed_is_no_source(tmp_path):
    assert source(tmp_path, raw="{").teams(NOW)["status"] is None
    assert source(tmp_path, raw="[]").teams(NOW)["reason"] == "no source: teams.json has no generated_at"
    assert source(tmp_path, feed={"sessions": []}).teams(NOW)["status"] is None


def test_junk_entries_do_not_break_the_page_data(tmp_path):
    feed = dict(FEED, sessions=["x", {"name": "Lead C"}], contractors=[None], budget="x", waiting_on_owner=[])
    got = source(tmp_path, feed).teams(NOW)["status"]
    assert [t["name"] for t in got["teams"]] == ["Lead C"]
    assert got["teams"][0]["state"] == "unknown"
    assert got["budget"]["week_pct"] is None


MACHINES = {
    "probed_at": "2026-10-01T13:49:00+00:00",
    "vm": {"state": "running", "lease": "held by Ann (T-1) since 10:00, 12 min left", "launcher": "active",
           "driver": "up", "sandboxes_known": True, "claims": [{"resource": "pcusb-vm", "text": "Ann T-1"}],
           "sandboxes": [{"name": "uirev48", "state": "running", "lease": "Bob (T-2) since 09:10, 20 min left"},
                         {"name": "dd2", "state": "stopped", "lease": "free"}]},
    "pi": {"online": True, "launcher": "running", "md5": "a" * 32, "claims": []},
    "psc": {"online": False, "launcher": "unknown", "md5": "", "claims": [{"resource": "psc", "text": "PM"}]},
    "other_claims": [],
}


def test_the_machines_block_is_passed_on(tmp_path):
    got = source(tmp_path, dict(FEED, machines=MACHINES)).teams(NOW)["status"]["machines"]
    assert got["probed_at"] == MACHINES["probed_at"]
    assert got["vm"]["lease"].startswith("held by Ann") and got["vm"]["driver"] == "up"
    assert got["vm"]["claims"] == [{"resource": "pcusb-vm", "text": "Ann T-1"}]
    assert [s["name"] for s in got["vm"]["sandboxes"]] == ["uirev48", "dd2"]
    assert got["pi"] == {"launcher": "running", "md5": "a" * 32, "online": True, "claims": []}
    assert got["psc"]["online"] is False and got["psc"]["claims"][0]["text"] == "PM"


def test_a_feed_without_machines_gives_an_empty_block(tmp_path):
    assert source(tmp_path, FEED).teams(NOW)["status"]["machines"] == {}


def test_a_junk_machines_block_does_not_break_the_page_data(tmp_path):
    got = source(tmp_path, dict(FEED, machines={"vm": "x", "pi": None, "psc": {"online": "yes"}})).teams(NOW)["status"]
    assert got["machines"]["vm"]["sandboxes"] == [] and got["machines"]["pi"]["online"] is None
    assert got["machines"]["psc"]["online"] is None
    assert source(tmp_path, dict(FEED, machines="x")).teams(NOW)["status"]["machines"] == {}
