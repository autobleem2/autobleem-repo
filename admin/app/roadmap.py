"""The roadmap tab's data: `docs/todo.md` and `docs/roadmap.md` from autobleem-main, parsed into rows and
milestones. Pure text in, pure data out - no network, no filesystem; the endpoints fetch the markdown
through the App's contents API and hand it here. See `autobleem-main`'s `docs/admin-roadmap-plan.md`.

The two names the panel's endpoints import: `parse_todo(markdown_text)` and
`parse_milestones(markdown_text)`.
"""
import re

_SECTION_RE = re.compile(r"^##\s+([A-Z])\b")
_ROW_ID_RE = re.compile(r"^[A-Z]\d+$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_DONE_RE = re.compile(r"^~~(?P<inner>.*?)~~\s*\*\*done\s+(?P<date>[\d-]+)\*\*", re.S)
_TEAM_RE = re.compile(r"Team:\s*([^,.()]+)")
_MILESTONE_HEADER_RE = re.compile(r"^\|\s*Milestone\s*\|.*Theme")


def split_cells(line):
    """A markdown table row's cells, split on `|` - but not a `|` inside a backtick span (todo.md has
    shell one-liners with pipes in them, e.g. `grep -q '...' | apt-cache ...`)."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells, cur, in_code = [], [], False
    for ch in body:
        if ch == "`":
            in_code = not in_code
            cur.append(ch)
        elif ch == "|" and not in_code:
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur))
    return [c.strip() for c in cells]


def _first_bold(text):
    m = _BOLD_RE.search(text)
    return m.group(1).strip() if m else None


def _team_of(text):
    m = _TEAM_RE.search(text)
    return m.group(1).strip() if m else None


def _title_and_done(what):
    """(title, done, done_date, done_by) - a done row's title is `~~**...**~~ **done <date>** (<who>)`;
    an open row's title is its first bold span, or the whole cell when it has none."""
    done = _DONE_RE.match(what)
    if not done:
        return _first_bold(what) or what.strip(), False, None, None
    inner, date = done.group("inner"), done.group("date")
    title = _first_bold(inner) or inner.strip()
    rest = what[done.end():].lstrip()
    by = re.match(r"^\(([^)]*)\)", rest)
    return title, True, date, (by.group(1).strip() if by else None)


def parse_todo(markdown_text):
    """`docs/todo.md` -> a list of row dicts `{id, section, title, text, where, size, who, ms, team, done,
    done_date, done_by}`, in file order. A row is `| ID | ... |` (`ID` = a letter + digits) under the
    nearest `## X - ...` heading; non-row lines (headings, the column header, the `|---|` separator,
    prose) are skipped."""
    rows = []
    section = None
    for line in markdown_text.splitlines():
        heading = _SECTION_RE.match(line)
        if heading:
            section = heading.group(1)
            continue
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if len(cells) < 6 or not _ROW_ID_RE.match(cells[0]):
            continue
        row_id, what, where, size, who, ms = cells[:6]
        title, done, done_date, done_by = _title_and_done(what)
        rows.append({
            "id": row_id,
            "section": section,
            "title": title,
            "text": what,
            "where": where,
            "size": size,
            "who": who,
            "ms": ms,
            "team": _team_of(what),
            "done": done,
            "done_date": done_date,
            "done_by": done_by,
        })
    return rows


def milestone_code(name):
    """The milestone name as `docs/roadmap.md`'s table spells it (`alpha2`, `beta1`, `rc1 -> 2.0.0`,
    `2.1+`) -> the short code `docs/todo.md`'s `Ms` column uses (`a2`, `b1`, `rc`, `later`)."""
    m = re.match(r"alpha(\d+)", name)
    if m:
        return "a" + m.group(1)
    m = re.match(r"beta(\d+)", name)
    if m:
        return "b" + m.group(1)
    if name.lower().startswith("rc"):
        return "rc"
    return "later"


def parse_milestones(markdown_text):
    """`docs/roadmap.md`'s milestone table (`## The milestones`) -> a list of dicts `{order, code, name,
    theme, gate, who, size}` in table order. `order` is the 0-based position, `code` the `todo.md`-style
    code (`milestone_code`)."""
    lines = markdown_text.splitlines()
    milestones = []
    in_table, past_separator = False, False
    for line in lines:
        if _MILESTONE_HEADER_RE.match(line):
            in_table, past_separator = True, False
            continue
        if not in_table:
            continue
        if not line.strip().startswith("|"):
            break
        if not past_separator:
            past_separator = True  # the `|---|---|...|` row under the header
            continue
        cells = split_cells(line)
        if len(cells) < 5:
            continue
        name = _first_bold(cells[0]) or cells[0]
        milestones.append({
            "order": len(milestones),
            "code": milestone_code(name),
            "name": name,
            "theme": cells[1],
            "gate": cells[2],
            "who": cells[3],
            "size": cells[4],
        })
    return milestones


def milestone_progress(rows, milestones):
    """One summary per milestone, in `milestones`' order: `done`/`open`/`total` rows, `pct` done, and
    `open_by_team` (team name -> open-row count, `"unassigned"` for a row with no `Team:`). Also returns
    the sorted list of `ms` codes in `rows` that no milestone claims (a milestone renamed or removed in
    `roadmap.md` while `todo.md` still points at its old code) - callers show those apart rather than
    silently dropping the rows."""
    known = {m["code"] for m in milestones}
    summaries = []
    for m in milestones:
        mine = [r for r in rows if r["ms"] == m["code"]]
        done = [r for r in mine if r["done"]]
        open_rows = [r for r in mine if not r["done"]]
        by_team = {}
        for r in open_rows:
            key = r["team"] or "unassigned"
            by_team[key] = by_team.get(key, 0) + 1
        total = len(mine)
        summaries.append({
            "code": m["code"],
            "name": m["name"],
            "theme": m["theme"],
            "gate": m["gate"],
            "done": len(done),
            "open": len(open_rows),
            "total": total,
            "pct": round(100 * len(done) / total, 1) if total else None,
            "open_by_team": by_team,
        })
    unknown_ms = sorted({r["ms"] for r in rows if r["ms"] and r["ms"] not in known})
    return summaries, unknown_ms


_OWNER_TEXT_RE = re.compile(
    r"owner'?s (?:decision|go|ok|approval)|the owner (?:chooses|decides|picks)"
    r"|waits? for the owner|pending the (?:owner'?s )?ok|parked by the owner",
    re.I,
)


def _who_is_owner(who):
    return "owner" in [w.strip().lower() for w in re.split(r"[+,/]| and | then ", who or "")]


def needs_owner(rows):
    """The open rows waiting on the owner: `Who` is (or includes) `owner`, or the text says it is waiting
    for the owner's decision/go/OK. One line each: `{id, title, why}`."""
    out = []
    for r in rows:
        if r["done"]:
            continue
        if _who_is_owner(r["who"]):
            out.append({"id": r["id"], "title": r["title"], "why": "who"})
            continue
        if _OWNER_TEXT_RE.search(r["text"]):
            out.append({"id": r["id"], "title": r["title"], "why": "text"})
    return out
