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
    assert got["budget"] == FEED["budget"]
    a, b = got["teams"]
    assert (a["name"], a["team"], a["state"]) == ("Lead A", "Lead Software · model-x", "working")
    assert [i["id"] for i in a["items"]] == ["TASK-1", "TASK-2"]
    assert a["note"] == "queued: TASK-9"
    assert (b["state"], b["items"], b["note"]) == ("idle", [], "")
    assert got["needs_owner"] == [{"id": "TASK-7", "kind": "session", "what": "", "howto": ""}]
    assert got["questions"] == []


def test_sessions_and_open_questions_for_the_owner(tmp_path):
    feed = dict(FEED, waiting_on_owner=[{"id": "PSC-TEST", "what": "the game on the console"}],
                owner_questions=[{"added": "Fri 02.10 01:40", "from": "PM", "question": "Which way?",
                                  "options": "A / B"}])
    got = source(tmp_path, feed).teams(NOW)["status"]
    assert got["needs_owner"] == [{"id": "PSC-TEST", "kind": "session", "what": "the game on the console",
                                   "howto": ""}]
    assert got["questions"] == [{"added": "Fri 02.10 01:40", "from": "PM", "question": "Which way?",
                                 "options": "A / B"}]


def test_a_session_without_slots_shows_its_task(tmp_path):
    feed = dict(FEED, contractors=[])
    a = source(tmp_path, feed).teams(NOW)["status"]["teams"][0]
    assert a["items"] == [{"id": "TASK-1", "what": "first task"}]


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
