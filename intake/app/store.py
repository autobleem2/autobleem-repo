"""Reading the test plans and reading/writing the data directory (the layout is in intake/README.md)."""
import glob
import json
import logging
import os
import re
import secrets
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

import yaml

from .config import PLATFORMS

ID_RE = re.compile(r"^[a-z0-9]{8}$")
CLAIM_RE = re.compile(r"^[a-z0-9]{16}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ISO = "%Y-%m-%dT%H:%M:%SZ"


class Refused(Exception):
    """A request that cannot be served; `status` is the HTTP code, the text goes to the client."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def new_id(n=8):
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def stamp(dt):
    return dt.astimezone(timezone.utc).strftime(ISO)


def parse_stamp(text):
    return datetime.strptime(text, ISO).replace(tzinfo=timezone.utc)


# The portal's data is shared with the admin panel through one fixed group (gid 10050 in both Dockerfiles): folders
# are group-writable with setgid, files group-readable, whatever the process umask says.
DIR_MODE = 0o2770
FILE_MODE = 0o640


def ensure_dir(path):
    """Create `path` and any missing parent below it with DIR_MODE (umask-proof)."""
    if os.path.isdir(path):
        return
    ensure_dir(os.path.dirname(path))
    try:
        os.mkdir(path)
    except FileExistsError:
        return
    os.chmod(path, DIR_MODE)


def write_atomic(path, data):
    """A temp file in the same folder, then rename: a reader sees the old file or the whole new one."""
    folder = os.path.dirname(path)
    ensure_dir(folder)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(path, obj):
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def version_key(tag):
    """The same order as tools/repo_index.py's version_key, without the publish-time tie-break."""
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-(.*))?$", tag)
    if not m:
        return (0, 0, 0, 0, (0, 0, 0, tag))
    major, minor, patch, suffix = m.groups()
    label = re.sub(r"-[0-9a-f]{7,40}$", "", suffix or "")
    ranks = {"pre": 0, "alpha": 1, "beta": 2, "rc": 3}
    lm = re.match(r"^(pre|alpha|beta|rc)(\d*)(?:\.(\d+))?$", label)  # alpha1.1: a point release of alpha1
    label_key = (ranks[lm.group(1)], int(lm.group(2) or 0), int(lm.group(3) or 0), "") if lm else (4, 0, 0, label)
    return (int(major), int(minor), int(patch or 0), 0 if suffix else 1, label_key)


class Store:
    def __init__(self, settings, clock):
        self.s = settings
        self.clock = clock
        self._plans = {}

    def prepare(self):
        """At start: the data directory and decisions/ (the panel writes there) with the shared modes."""
        try:
            ensure_dir(os.path.join(self.s.data_dir, "decisions"))
        except OSError as exc:
            logging.getLogger("intake").warning("cannot prepare the data directory: %s", exc)

    # ---- settings.json

    def knobs(self):
        raw = read_json(os.path.join(self.s.data_dir, "settings.json"), {})
        if not isinstance(raw, dict):
            raw = {}

        def positive(key, default):
            v = raw.get(key, default)
            return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else default
        return positive("target_passes", self.s.target_passes), positive("claim_hours", self.s.claim_hours)

    # ---- test plans (the site's testplans/, read-only)

    def versions(self):
        try:
            names = [n for n in os.listdir(self.s.plans_dir)
                     if VERSION_RE.match(n) and os.path.isdir(os.path.join(self.s.plans_dir, n))]
        except OSError:
            return []
        return sorted(names, key=version_key)

    def current_version(self):
        index = read_json(os.path.join(self.s.plans_dir, "index.json"), {})
        cur = index.get("current") if isinstance(index, dict) else None
        if isinstance(cur, str) and cur in self.versions():
            return cur
        versions = self.versions()
        return versions[-1] if versions else None

    def plan(self, platform, version):
        """The parsed plan, or Refused for an unknown platform/version."""
        if platform not in PLATFORMS:
            raise Refused("unknown platform")
        if not isinstance(version, str) or not VERSION_RE.match(version) or version not in self.versions():
            raise Refused("unknown version")
        path = os.path.join(self.s.plans_dir, version, platform + ".yaml")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            raise Refused("no test plan for this platform and version")
        cached = self._plans.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        sections = []
        for sec in raw.get("sections") or []:
            sections.append({
                "id": str(sec["id"]), "title": sec.get("title", ""), "minutes": sec.get("minutes", 0),
                "needs": sec.get("needs", ""), "steps": [str(st["id"]) for st in sec.get("steps") or []]})
        plan = {"sections": sections}
        self._plans[path] = (mtime, plan)
        return plan

    def platforms_of(self, version):
        return [p for p in PLATFORMS if os.path.isfile(os.path.join(self.s.plans_dir, version, p + ".yaml"))]

    # ---- claims

    def _claim_path(self, platform, version, claim):
        return os.path.join(self.s.data_dir, "claims", platform, version, claim + ".json")

    def get_claim(self, platform, version, claim):
        if not isinstance(claim, str) or not CLAIM_RE.match(claim):
            return None
        return read_json(self._claim_path(platform, version, claim))

    def claim_open(self, rec):
        """Not closed and not past its expiry (worked out here, no timer)."""
        try:
            return rec.get("closed_by") is None and parse_stamp(rec["expires"]) > self.clock()
        except (KeyError, ValueError, AttributeError):
            return False

    def open_claims(self, platform, version):
        counts = {}
        for path in glob.glob(os.path.join(self.s.data_dir, "claims", platform, version, "*.json")):
            rec = read_json(path)
            if isinstance(rec, dict) and self.claim_open(rec):
                counts[rec.get("section")] = counts.get(rec.get("section"), 0) + 1
        return counts

    def make_claim(self, platform, version, section):
        _, hours = self.knobs()
        now = self.clock()
        rec = {"claim": new_id(16), "section": section, "made": stamp(now),
               "expires": stamp(now + timedelta(hours=hours)), "closed_by": None}
        write_json(self._claim_path(platform, version, rec["claim"]), rec)
        return rec

    def close_claim(self, platform, version, rec, closed_by):
        rec = dict(rec, closed_by=closed_by)
        write_json(self._claim_path(platform, version, rec["claim"]), rec)

    # ---- results

    def results(self, platform, version):
        out = []
        for path in sorted(glob.glob(os.path.join(self.s.data_dir, "testplans", platform, version, "*.json"))):
            rec = read_json(path)
            if isinstance(rec, dict):
                out.append(rec)
        return out

    def passes(self, platform, version):
        counts = {}
        for rec in self.results(platform, version):
            counts[rec.get("section")] = counts.get(rec.get("section"), 0) + 1
        return counts

    def neediest(self, platform, version):
        """(section, passes): fewest passes, then fewest open claims, then plan order."""
        sections = self.plan(platform, version)["sections"]
        if not sections:
            raise Refused("the plan has no sections", 404)
        passes = self.passes(platform, version)
        open_claims = self.open_claims(platform, version)
        best = min(enumerate(sections),
                   key=lambda t: (passes.get(t[1]["id"], 0), open_claims.get(t[1]["id"], 0), t[0]))[1]
        return best, passes.get(best["id"], 0)

    def store_result(self, platform, version, record):
        day = self.clock().strftime("%Y-%m-%dT%H%M%S")
        path = os.path.join(self.s.data_dir, "testplans", platform, version, "%s-%s.json" % (day, record["id"]))
        write_json(path, record)

    # ---- issues

    def store_issue(self, record, logs):
        day = self.clock().strftime("%Y-%m-%d")
        folder = os.path.join(self.s.data_dir, "issues", day, record["id"])
        if logs is not None:
            write_atomic(os.path.join(folder, "logs.zip"), logs)
        write_json(os.path.join(folder, "report.json"), record)   # the report appears last

    # ---- status

    def find_report(self, rid):
        if not ID_RE.match(rid):
            return None
        for path in glob.glob(os.path.join(self.s.data_dir, "issues", "*", rid, "report.json")):
            rec = read_json(path)
            if isinstance(rec, dict):
                return "issue", rec.get("received")
        for path in glob.glob(os.path.join(self.s.data_dir, "testplans", "*", "*", "*-%s.json" % rid)):
            rec = read_json(path)
            if isinstance(rec, dict):
                return "testplan", rec.get("received")
        return None

    def decision_state(self, rid):
        rec = read_json(os.path.join(self.s.data_dir, "decisions", rid + ".json"))
        state = rec.get("state") if isinstance(rec, dict) else None
        return state if isinstance(state, str) and state else "received"


def check_zip(data, max_total, max_entries):
    """Refuse a non-zip, an archive with a path that escapes (`..`, a leading `/` or `\\`) and one that
    would unpack to more than max_total. The archive is only listed, never extracted."""
    import io
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise Refused("logs must be a .zip file")
    if len(infos) > max_entries:
        raise Refused("the zip has too many files")
    total = 0
    for info in infos:
        name = info.filename
        parts = re.split(r"[\\/]", name)
        if name.startswith(("/", "\\")) or ".." in parts or re.match(r"^[A-Za-z]:", name):
            raise Refused("the zip has a file name that is not allowed")
        total += info.file_size
        if total > max_total:
            raise Refused("the zip is too large when unpacked")
