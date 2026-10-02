"""PLATFORM-9 part 2: `docs/bugs.md`, parsed by `app/bugs.py` and read by `app/bugs_source.py` over a fake
contents API - the same fake `test_roadmap_source.py` uses for the roadmap tab.

    cd admin && python -m pytest -q
"""
import base64
import logging
import os

from app.bugs import filter_bugs, matches_platform, matches_state, parse_bugs, sort_bugs
from app.bugs_source import BugsSource
from app.config import Settings
from app.github import GitHubError


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


def source(text):
    return BugsSource(FakeContents({"docs/bugs.md": text}), Settings())


HEADER = "| BUG | Title | Platform | Severity | State | Found | Fix |\n|---|---|---|---|---|---|---|\n"

GOOD = HEADER + "\n".join([
    "| BUG-1 | A pad wizard step never finishes | psc | major | confirmed | console session, 2026-09-27 | [TOOLS-9](todo.md) |",
    "| BUG-2 | Bluetooth stays blocked after a reboot | rpi | major | open | Pi 400 test, 2026-09-27 | - |",
    "| BUG-3 | A log line is written twice | all | minor | wontfix | console session, 2026-09-27 | - |",
    "| BUG-4 | Same as BUG-2, filed before it was found to be one | rpi, pcusb | major | duplicate of BUG-2 | Pi 400 test, 2026-09-27 | - |",
    "| BUG-5 | A build flake, fixed and verified | win, pcusb | minor | closed | CI run, 2026-09-27 | [RELEASE-1](todo.md) |",
    "| BUG-6 | A blocker so the sort order is checked | psc | blocker | fixing | console session, 2026-09-27 | [TOOLS-1](todo.md) |",
])


def test_reads_develop_of_autobleem_main():
    s = source(GOOD)
    s.bugs()
    assert s.gh.paths == ["/repos/autobleem2/autobleem-main/contents/docs/bugs.md?ref=develop"]


def test_no_file_yet():
    assert BugsSource(FakeContents({}), Settings()).bugs() == []


def test_parses_every_column():
    bugs = parse_bugs(GOOD)
    assert len(bugs) == 6
    b1 = bugs[0]
    assert b1 == {"id": "BUG-1", "number": 1, "title": "A pad wizard step never finishes",
                  "platforms": ["psc"], "severity": "major", "state": "confirmed", "duplicate_of": None,
                  "found": "console session, 2026-09-27", "fix_id": "TOOLS-9", "fix_ids": ["TOOLS-9"],
                  "fix_note": None}


def test_all_platform():
    bugs = parse_bugs(GOOD)
    b3 = next(b for b in bugs if b["id"] == "BUG-3")
    assert b3["platforms"] == ["all"]


def test_duplicate_of():
    bugs = parse_bugs(GOOD)
    b4 = next(b for b in bugs if b["id"] == "BUG-4")
    assert b4["state"] == "duplicate"
    assert b4["duplicate_of"] == "BUG-2"


def test_fix_dash_is_none():
    bugs = parse_bugs(GOOD)
    b2 = next(b for b in bugs if b["id"] == "BUG-2")
    assert b2["fix_id"] is None


def test_non_bug_rows_are_ignored_quietly(caplog):
    text = HEADER + "| ID | not a bug row | x | y | z | w | v |\n"
    with caplog.at_level(logging.WARNING):
        bugs = parse_bugs(text)
    assert bugs == []
    assert not caplog.records


def test_odd_values_are_kept_not_dropped(caplog):
    """A value the parser does not know no longer costs the whole row (that hid 34 of 41 bugs on the panel)."""
    rows = [
        "| BUG-90 | bad platform | mars | major | open | somewhere | - |",
        "| BUG-91 | odd severity | psc | critical | open | somewhere | - |",
        "| BUG-92 | odd state | psc | major | in-limbo | somewhere | - |",
        "| BUG-93 | a sentence as the fix | psc | major | open | somewhere | see TOOLS-9 |",
    ]
    with caplog.at_level(logging.WARNING):
        bugs = parse_bugs(HEADER + "\n".join(rows) + "\n")
    assert [b["id"] for b in bugs] == ["BUG-90", "BUG-91", "BUG-92", "BUG-93"]
    assert bugs[0]["platforms"] == []
    assert bugs[1]["severity"] == "critical"
    assert bugs[2]["state"] == "in-limbo"
    assert (bugs[3]["fix_id"], bugs[3]["fix_note"]) == (None, "see TOOLS-9")
    assert not caplog.records


def test_a_row_with_too_few_cells_is_skipped_and_logged(caplog):
    text = HEADER + "| BUG-94 | too few columns | psc | major |\n| BUG-95 | fine | psc | minor | new | x | - |\n"
    with caplog.at_level(logging.WARNING):
        bugs = parse_bugs(text)
    assert [b["id"] for b in bugs] == ["BUG-95"]
    assert len(caplog.records) == 1


def _today():
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "bugs_today.md"), encoding="utf-8") as f:
        return {b["id"]: b for b in parse_bugs(f.read())}


def test_todays_format_loses_no_row(caplog):
    with caplog.at_level(logging.WARNING):
        bugs = _today()
    assert len(bugs) == 13
    assert not caplog.records


def test_todays_four_states():
    bugs = _today()
    assert {b["state"] for b in bugs.values()} == {"new", "in progress", "done", "closed", "duplicate"}
    open_bugs, closed_bugs = sort_bugs(list(bugs.values()))
    # `done` is folded away with the closed ones (like the Tasks tab); blocker > major > minor > trivial
    assert [b["id"] for b in open_bugs] == ["BUG-6", "BUG-21", "BUG-30", "BUG-13", "BUG-25"]
    assert [b["id"] for b in closed_bugs] == ["BUG-1", "BUG-9", "BUG-11", "BUG-12", "BUG-23", "BUG-33",
                                              "BUG-38", "BUG-40"]


def test_todays_platform_cells_with_notes():
    bugs = _today()
    assert bugs["BUG-9"]["platforms"] == ["psc", "rpi", "pcusb", "win"]
    assert bugs["BUG-25"]["platforms"] == ["win"]
    assert bugs["BUG-30"]["platforms"] == ["psc"]
    assert bugs["BUG-33"]["platforms"] == ["rpi"]


def test_todays_fix_cells():
    bugs = _today()
    assert (bugs["BUG-21"]["fix_id"], bugs["BUG-21"]["fix_ids"]) == ("CONSOLE-13", ["CONSOLE-13", "CONSOLE-12"])
    assert (bugs["BUG-21"]["fix_note"]) is None
    assert (bugs["BUG-23"]["fix_id"], bugs["BUG-23"]["fix_note"]) == (None, "autobleem-core 8e50061")
    assert bugs["BUG-11"]["fix_note"] == "wontfix"
    assert (bugs["BUG-12"]["fix_id"], bugs["BUG-12"]["fix_note"]) == ("EMU-8", "[EMU-8](todo.md), wontfix")
    assert bugs["BUG-13"]["fix_id"] is None and bugs["BUG-13"]["fix_note"] is None


def test_todays_short_row_and_trivial_severity():
    bugs = _today()
    assert bugs["BUG-33"]["state"] == "done" and bugs["BUG-33"]["found"] == "" and bugs["BUG-33"]["fix_id"] is None
    assert bugs["BUG-38"]["severity"] == "trivial"


def test_a_closed_bug_whose_fix_cell_says_duplicate():
    bug = _today()["BUG-40"]
    assert (bug["state"], bug["duplicate_of"]) == ("duplicate", "BUG-13")


def test_sort_open_first_by_severity_then_number():
    bugs = parse_bugs(GOOD)
    open_bugs, closed_bugs = sort_bugs(bugs)
    assert [b["id"] for b in open_bugs] == ["BUG-6", "BUG-1", "BUG-2"]  # blocker, then major x2 by number
    assert [b["id"] for b in closed_bugs] == ["BUG-3", "BUG-4", "BUG-5"]  # wontfix, duplicate, closed - by number


def test_matches_platform_all_bug_shows_under_any_platform():
    bug = {"platforms": ["all"]}
    assert matches_platform(bug, "psc")
    assert matches_platform(bug, "win")
    assert matches_platform(bug, "")


def test_matches_platform_specific():
    bug = {"platforms": ["rpi", "pcusb"]}
    assert matches_platform(bug, "rpi")
    assert matches_platform(bug, "pcusb")
    assert not matches_platform(bug, "psc")


def test_matches_state():
    bug = {"state": "duplicate"}
    assert matches_state(bug, "duplicate")
    assert not matches_state(bug, "open")
    assert matches_state(bug, "")


def test_filter_bugs_combines_both():
    bugs = parse_bugs(GOOD)
    got = filter_bugs(bugs, state="open", platform="rpi")
    assert [b["id"] for b in got] == ["BUG-2"]  # BUG-4 is "duplicate", not "open"; BUG-1 is psc, not rpi


def test_filter_bugs_platform_all_included_in_specific_platform():
    bugs = parse_bugs(GOOD)
    got = filter_bugs(bugs, state="", platform="win")
    assert {b["id"] for b in got} == {"BUG-3", "BUG-5"}  # BUG-3 is "all", BUG-5 lists win directly
