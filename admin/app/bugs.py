"""The Bugs tab's data: `docs/bugs.md` from autobleem-main, parsed into bug dicts. Pure text (and pure
data) in, pure data out - no network, no filesystem; `bugs_source.py`'s `BugsSource` fetches the markdown
and hands it here, the same split `roadmap.py`/`roadmap_source.py` use for the roadmap tab.

The table (Harriet's format, PLATFORM-9 part 1, `docs/bugs.md`'s own header names the columns and the
allowed values for each):

    | BUG | Title | Platform | Severity | State | Found | Fix |

`parse_bugs(markdown_text)` -> a list of bug dicts `{id, number, title, platforms, severity, state,
duplicate_of, found, fix_id}`, in file order. A row that does not fit the format is skipped, with a
warning logged - the panel must never crash on a stray hand-edit of the file.
"""
import logging
import re

from .roadmap import split_cells

logger = logging.getLogger(__name__)

_BUG_ID_RE = re.compile(r"^BUG-(\d+)$")
_PLATFORM_WORDS = {"psc", "rpi", "pcusb", "win"}
_SEVERITIES = {"blocker", "major", "minor"}
_OPEN_STATES = {"open", "confirmed", "fixing", "fixed-untested"}
_CLOSED_STATES = {"closed", "wontfix"}
_DUPLICATE_RE = re.compile(r"^duplicate of (BUG-\d+)$")
_FIX_RE = re.compile(r"^\[([A-Za-z0-9][A-Za-z0-9-]{0,63})\]\(todo\.md\)$")

# lower number = shown first among the open bugs
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2}


def _parse_platforms(cell):
    """"all", or a comma list of platform words - None when it is neither (a malformed row)."""
    cell = cell.strip()
    if cell == "all":
        return ["all"]
    parts = [p.strip() for p in cell.split(",") if p.strip()]
    if not parts or any(p not in _PLATFORM_WORDS for p in parts):
        return None
    return parts


def _parse_state(cell):
    """(state, duplicate_of) - state is one of the seven table values, `duplicate` standing in for
    "duplicate of BUG-N" (duplicate_of carries the N); (None, None) when the cell matches none of them."""
    cell = cell.strip()
    if cell in _OPEN_STATES or cell in _CLOSED_STATES:
        return cell, None
    m = _DUPLICATE_RE.match(cell)
    if m:
        return "duplicate", m.group(1)
    return None, None


def _parse_fix(cell):
    """The `Fix` cell: a todo row id, None for "-", or False for anything else (malformed)."""
    cell = cell.strip()
    if cell == "-":
        return None
    m = _FIX_RE.match(cell)
    return m.group(1) if m else False


def parse_bugs(markdown_text):
    bugs = []
    for lineno, line in enumerate(markdown_text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if len(cells) < 7:
            continue
        bug_id = cells[0].strip()
        m = _BUG_ID_RE.match(bug_id)
        if not m:
            continue  # the header row, the `|---|` separator, or prose that happens to start with `|`
        title, platform_cell, severity_cell, state_cell, found, fix_cell = (c.strip() for c in cells[1:7])
        platforms = _parse_platforms(platform_cell)
        severity = severity_cell if severity_cell in _SEVERITIES else None
        state, duplicate_of = _parse_state(state_cell)
        fix_id = _parse_fix(fix_cell)
        if platforms is None or severity is None or state is None or fix_id is False:
            logger.warning("docs/bugs.md line %d: malformed row for %s, skipped", lineno, bug_id)
            continue
        bugs.append({
            "id": bug_id,
            "number": int(m.group(1)),
            "title": title,
            "platforms": platforms,
            "severity": severity,
            "state": state,
            "duplicate_of": duplicate_of,
            "found": found,
            "fix_id": fix_id,
        })
    return bugs


def is_open(bug):
    """Everything not closed/wontfix/duplicate - the Bugs tab's main list."""
    return bug["state"] not in ("closed", "wontfix", "duplicate")


def sort_bugs(bugs):
    """(open_bugs, closed_bugs): open first, sorted blocker > major > minor then by number; the rest
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
    """Whether `bug` shows under a `state` filter - one of the seven table values, "duplicate" included."""
    return not state or bug["state"] == state


def filter_bugs(bugs, state="", platform=""):
    """The rows a state/platform filter pair leaves, in the input's order - callers sort before or after,
    whichever they need."""
    return [b for b in bugs if matches_state(b, state) and matches_platform(b, platform)]
