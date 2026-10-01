"""app/roadmap.py over the trimmed fixtures in tests/fixtures/ (real rows cut down to the parser's
quirks: a struck-through row, a `|` inside backticks, a missing `Team:`, and an unknown milestone code).

    cd admin && python -m pytest -q
"""
import os

import pytest

from app.roadmap import (
    milestone_code,
    milestone_progress,
    needs_owner,
    parse_milestones,
    parse_todo,
    split_cells,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def todo_rows():
    return parse_todo(_read("todo.md"))


@pytest.fixture
def milestones():
    return parse_milestones(_read("roadmap.md"))


def by_id(rows, row_id):
    return next(r for r in rows if r["id"] == row_id)


# ------------------------------------------------------------------ split_cells


def test_split_cells_ignores_a_pipe_inside_backticks():
    line = "| K14 | the probe `a | b` and `c` | installer | S | dev | a2 |"
    assert split_cells(line) == ["K14", "the probe `a | b` and `c`", "installer", "S", "dev", "a2"]


def test_split_cells_plain_row():
    assert split_cells("| R1 | text | where | M | dev | a2 |") == ["R1", "text", "where", "M", "dev", "a2"]


# ------------------------------------------------------------------ parse_todo


def test_parse_todo_row_key_set(todo_rows):
    assert set(todo_rows[0].keys()) == {"id", "section", "title", "text", "where", "size", "who", "ms",
                                        "team", "done", "done_date", "done_by", "state"}


def test_parse_todo_row_count_and_sections(todo_rows):
    assert [r["id"] for r in todo_rows] == ["R1", "R9", "R21", "R99", "K14", "D16"]
    assert by_id(todo_rows, "R1")["section"] == "R"
    assert by_id(todo_rows, "K14")["section"] == "K"
    assert by_id(todo_rows, "D16")["section"] == "D"


def test_parse_todo_open_row_with_team(todo_rows):
    r1 = by_id(todo_rows, "R1")
    assert r1["title"] == "Replace `v2.0.0-alpha2` with the new alpha2"
    assert r1["team"] == "infrastructure"
    assert r1["where"] == "all component repos, site"
    assert r1["size"] == "M"
    assert r1["who"] == "dev"
    assert r1["ms"] == "a2"
    assert r1["done"] is False
    assert r1["done_date"] is None
    assert r1["done_by"] is None


def test_parse_todo_struck_through_done_row(todo_rows):
    r21 = by_id(todo_rows, "R21")
    assert r21["done"] is True
    assert r21["title"] == "A PC test machine + a second CI runner"
    assert r21["done_date"] == "2026-09-27"
    assert r21["done_by"] == "Wren Aldercroft"
    assert r21["team"] == "task force"
    # the full markdown (including the strikethrough) is still in `text` for the row's expanded view
    assert r21["text"].startswith("~~**A PC test machine")


def test_parse_todo_row_with_pipe_inside_backticks_is_not_split(todo_rows):
    k14 = by_id(todo_rows, "K14")
    assert k14["where"] == "installer, pcusb, rpi"
    assert k14["who"] == "dev"
    assert k14["ms"] == "a2"
    assert "grep -q '^  Candidate: [^(]'" in k14["text"]
    assert k14["team"] == "software/ui"


def test_parse_todo_row_with_no_team(todo_rows):
    r99 = by_id(todo_rows, "R99")
    assert r99["team"] is None
    assert r99["ms"] == "a4"  # deliberately absent from the trimmed roadmap.md fixture


def test_parse_todo_owner_who_and_owner_text(todo_rows):
    r9 = by_id(todo_rows, "R9")
    assert r9["who"] == "owner"
    assert r9["team"] is None
    d16 = by_id(todo_rows, "D16")
    assert d16["who"] == "dev"
    assert "pending the owner's OK" in d16["text"]


def test_parse_todo_ignores_non_row_lines():
    text = "# Title\n\nSome prose with | a pipe | in it.\n\n## R - Release\n\n| ID | What | Where | Size | Who | Ms |\n|---|---|---|---|---|---|\n| R1 | x | y | S | dev | a2 |\n"
    rows = parse_todo(text)
    assert [r["id"] for r in rows] == ["R1"]


def test_parse_todo_area_word_ids():
    text = ("## RELEASE - Release and process\n\n| ID | What | Where | Size | Who | Ms |\n|---|---|---|---|---|---|\n"
            "| RELEASE-1 | x | y | S | dev | a2 |\n\n## HWTEST - Hardware proofs\n\n"
            "| ID | What | Where | Size | Who | Ms |\n|---|---|---|---|---|---|\n| HWTEST-12 | z | y | S | tester | a3 |\n")
    rows = parse_todo(text)
    assert [(r["id"], r["section"]) for r in rows] == [("RELEASE-1", "RELEASE"), ("HWTEST-12", "HWTEST")]


def test_parse_todo_legacy_rows_get_a_state(todo_rows):
    assert by_id(todo_rows, "R21")["state"] == "done"
    assert by_id(todo_rows, "R1")["state"] == "new"


def test_parse_todo_state_column_of_2026_10_01():
    """The hub's todo.md since 2026-10-01: a seventh `State` column (new / in progress / done / closed)."""
    rows = parse_todo(_read("todo_state.md"))
    assert [(r["id"], r["state"], r["done"]) for r in rows] == [
        ("RELEASE-3", "new", False), ("UIREV-40", "in progress", False), ("UIREV-41", "done", True),
        ("UIREV-2", "closed", True), ("EMU-17", "new", False)]
    assert by_id(rows, "UIREV-2")["title"].startswith("The d-pad hint arrows are readable")
    assert by_id(rows, "UIREV-41")["done_date"] is None  # no strike-through, so no date
    assert by_id(rows, "EMU-17")["ms"] == "EMU-16"  # a typo in the source stays as written
    assert by_id(rows, "UIREV-40")["ms"] == "alpha1"


def test_the_state_column_beats_the_strike_through():
    text = ("## UIREV - x\n\n| ID | What | Where | Size | Who | Ms | State |\n|---|---|---|---|---|---|---|\n"
            "| UIREV-1 | ~~**x**~~ **done 2026-09-29** (Hector) | y | S | dev | a2 | in progress |\n")
    row = parse_todo(text)[0]
    assert row["state"] == "in progress" and row["done"] is False


def test_the_alpha1_milestone_code():
    assert milestone_code("alpha1") == "a1"


# ------------------------------------------------------------------ parse_milestones / milestone_code


def test_milestone_code():
    assert milestone_code("alpha2") == "a2"
    assert milestone_code("alpha10") == "a10"
    assert milestone_code("beta1") == "b1"
    assert milestone_code("rc1 -> 2.0.0") == "rc"
    assert milestone_code("2.1+") == "later"


def test_parse_milestones(milestones):
    # list order IS the roadmap order - no separate "order" key
    assert [milestone_code(m["name"]) for m in milestones] == ["a2", "a3", "b1", "rc", "later"]
    a2 = milestones[0]
    assert a2["name"] == "alpha2"
    assert a2["theme"] == "Ship what is already built; make the release train work"
    assert a2["gate"] == "`promote alpha` runs green end to end"


def test_parse_milestones_key_set(milestones):
    assert set(milestones[0].keys()) == {"name", "theme", "gate"}


def test_parse_milestones_ignores_the_other_tables(milestones):
    # "Where we are" (above "The milestones") has a two-column header the parser must not mistake for it
    assert len(milestones) == 5


# ------------------------------------------------------------------ milestone_progress


def test_milestone_progress_counts_done_and_open_by_team(todo_rows, milestones):
    summaries, unknown_ms = milestone_progress(todo_rows, milestones)
    by_code = {s["code"]: s for s in summaries}
    a2 = by_code["a2"]
    # a2 has R1 (open, infrastructure), R21 (done, task force), K14 (open, software/ui)
    assert a2["done"] == 1
    assert a2["open"] == 2
    assert a2["total"] == 3
    assert a2["pct"] == pytest.approx(33.3, abs=0.1)
    assert a2["open_by_team"] == {"infrastructure": 1, "software/ui": 1}
    # rc has R9 (open, no team)
    rc = by_code["rc"]
    assert rc["done"] == 0 and rc["open"] == 1
    assert rc["open_by_team"] == {"unassigned": 1}
    # a3, beta1, later exist with zero rows and no division-by-zero
    assert by_code["a3"]["total"] == 0 and by_code["a3"]["pct"] is None
    # R99's "a4" is not a known milestone code - reported apart, not silently dropped
    assert unknown_ms == ["a4"]


def test_milestone_progress_empty_inputs():
    summaries, unknown_ms = milestone_progress([], [])
    assert summaries == []
    assert unknown_ms == []


# ------------------------------------------------------------------ needs_owner


def test_needs_owner(todo_rows):
    candidates = {c["id"]: c["why"] for c in needs_owner(todo_rows)}
    assert candidates["R9"] == "who"  # Who column is "owner"
    assert candidates["D16"] == "text"  # "pending the owner's OK" in the text, Who is "dev"
    assert "R1" not in candidates  # Who is "dev", nothing in the text says it waits on the owner
    assert "R21" not in candidates  # done rows are never "needs you"
