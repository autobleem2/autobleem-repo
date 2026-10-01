"""The Bugs tab's data: `docs/bugs.md` from autobleem-main, parsed into bug dicts. Pure text (and pure
data) in, pure data out - no network, no filesystem; `bugs_source.py`'s `BugsSource` fetches the markdown
and hands it here, the same split `roadmap.py`/`roadmap_source.py` use for the roadmap tab.

The table (`docs/bugs.md`'s own header names the columns):

    | BUG | Title | Platform | Severity | State | Found | Fix |

The hub's State is one of four values, the same four as every todo row: `new`, `in progress`, `done` (the fix is
merged, the check is left) and `closed`. The older seven (`open`, `confirmed`, `fixing`, `fixed-untested`,
`wontfix`, `duplicate of BUG-N`) still parse. The cells are free text in practice - a platform with a note
(`win (dev build)`), a Fix cell that is a commit or a sentence - so the parser never drops a row for a value it
does not know: it keeps what it can read (`platforms`, `fix_id`) and carries the rest as text (`fix_note`).

`parse_bugs(markdown_text)` -> a list of bug dicts `{id, number, title, platforms, severity, state,
duplicate_of, found, fix_id, fix_ids, fix_note}`, in file order. Only a line that is not a bug row at all is
skipped; a bug row with too few cells is skipped with a warning logged - the panel must never crash on a stray
hand-edit of the file.
"""
import logging
import re

from .roadmap import split_cells

logger = logging.getLogger(__name__)

_BUG_ID_RE = re.compile(r"^BUG-(\d+)$")
_PLATFORM_RE = re.compile(r"\b(psc|rpi|pcusb|win|all)\b", re.I)
_DUPLICATE_RE = re.compile(r"duplicate of (BUG-\d+)", re.I)
_FIX_LINK_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9-]{0,63})\]\([^)]*todo\.md[^)]*\)")
_MIN_CELLS = 5  # BUG | Title | Platform | Severity | State - the rest may be missing on a hand-edited row

# lower number = shown first among the open bugs
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "trivial": 3}


def _parse_platforms(cell):
    """The platform words of a cell: ["all"], or the platforms in the order written. A note after the list
    (`win (dev build)`, `psc (others unchecked) **PSC 2026-10-01 ...**`) is ignored: only the part before the
    first `(` or `*` counts, unless it names no platform at all (then the whole cell is searched). [] when the
    cell names none."""
    head = re.split(r"[(*;]", cell, maxsplit=1)[0]
    words = [w.lower() for w in _PLATFORM_RE.findall(head)] or [w.lower() for w in _PLATFORM_RE.findall(cell)]
    if "all" in words:
        return ["all"]
    return list(dict.fromkeys(words))


def _parse_state(cell, fix_cell=""):
    """(state, duplicate_of): the table's value - `duplicate` standing in for "duplicate of BUG-N" (written in
    the State cell, or, as the hub's format has it, in the Fix cell of a closed bug) - or the cell's own text
    (lower-cased) when it is none of the known ones, so an unknown state still shows."""
    state = cell.strip().strip("*").strip().lower()
    dup = _DUPLICATE_RE.search(state) or _DUPLICATE_RE.search(fix_cell)
    if state.startswith("duplicate") or (state == "closed" and dup):
        return "duplicate", dup.group(1).upper() if dup else None
    return state, None


def _parse_fix(cell):
    """(fix_ids, fix_note): the todo row ids linked in the Fix cell, and the cell's text when it holds more than
    those links (a commit, a sentence, `wontfix`); (list, None) for a bare link list, ([], None) for `-`."""
    cell = cell.strip()
    if cell in ("", "-"):
        return [], None
    ids = _FIX_LINK_RE.findall(cell)
    rest = _FIX_LINK_RE.sub("", cell).strip(" ,;")
    return ids, (cell if rest else None)


def parse_bugs(markdown_text):
    bugs = []
    for lineno, line in enumerate(markdown_text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        m = _BUG_ID_RE.match(cells[0].strip())
        if not m:
            continue  # the header row, the `|---|` separator, or prose that happens to start with `|`
        bug_id = cells[0].strip()
        if len(cells) < _MIN_CELLS:
            logger.warning("docs/bugs.md line %d: %s has too few columns, skipped", lineno, bug_id)
            continue
        title, platform_cell, severity_cell, state_cell, found, fix_cell = (cells[1:7] + [""] * 6)[:6]
        severity = severity_cell.strip().strip("*").strip().lower()
        state, duplicate_of = _parse_state(state_cell, fix_cell)
        fix_ids, fix_note = _parse_fix(fix_cell)
        bugs.append({
            "id": bug_id,
            "number": int(m.group(1)),
            "title": title,
            "platforms": _parse_platforms(platform_cell),
            "severity": severity,
            "state": state,
            "duplicate_of": duplicate_of,
            "found": found,
            "fix_id": fix_ids[0] if fix_ids else None,
            "fix_ids": fix_ids,
            "fix_note": fix_note,
        })
    return bugs


def is_open(bug):
    """Everything not closed/wontfix/duplicate - the Bugs tab's main list. `done` is open: the fix is merged
    but the check is left, and only QA closes a bug."""
    return bug["state"] not in ("closed", "wontfix", "duplicate")


def sort_bugs(bugs):
    """(open_bugs, closed_bugs): open first, sorted blocker > major > minor > trivial then by number; the rest
    (closed/wontfix/duplicate, for the folded section) sorted by number."""
    open_bugs = sorted((b for b in bugs if is_open(b)),
                       key=lambda b: (SEVERITY_ORDER.get(b["severity"], 99), b["number"]))
    closed_bugs = sorted((b for b in bugs if not is_open(b)), key=lambda b: b["number"])
    return open_bugs, closed_bugs


def matches_platform(bug, platform):
    """Whether `bug` shows under a `platform` filter (psc/rpi/pcusb/win): its own platforms list names it,
    or the bug is tagged "all" (affects every platform, so it belongs under any single one too)."""
    if not platform:
        return True
    return platform in bug["platforms"] or bug["platforms"] == ["all"]


def matches_state(bug, state):
    """Whether `bug` shows under a `state` filter - a table value, "duplicate" included."""
    return not state or bug["state"] == state


def filter_bugs(bugs, state="", platform=""):
    """The rows a state/platform filter pair leaves, in the input's order - callers sort before or after,
    whichever they need."""
    return [b for b in bugs if matches_state(b, state) and matches_platform(b, platform)]
