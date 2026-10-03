"""The download counter: how many times each file of the site was downloaded, per day.

The site is static files served by Caddy, so nothing sits in the download path. Caddy writes a JSON access log
(docker/repo/Caddyfile, `log`), and this module reads it incrementally into a small SQLite file in the panel's
data directory. What is stored: a day (UTC), a path and a count - no IP address, no user agent, no header. The
log itself never holds an IP or a header either (Caddy's log filter deletes them), and bots are kept out of it
by Caddy (`log_skip`).

What counts: a GET answered with 200 for a file of a download type (`DOWNLOAD_EXT`), outside the panel's own
paths. A HEAD, a 304 (cache check), a 404 and a 206 (a resumed or ranged download - its first request was
already counted) do not.

The read is rotation-safe and never counts a line twice: every log file is told apart by its inode, its read
offset is saved in the same SQLite transaction as the counts it produced, and only whole lines are read.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit

DOWNLOAD_EXT = (".zip", ".gz", ".tgz", ".xz", ".bz2", ".zst", ".7z", ".rar", ".tar", ".img", ".iso", ".bin",
                ".pdf", ".exe", ".msi", ".deb", ".apk")
SKIP_PREFIX = ("admin/", "oauth2/")
PLATFORMS = ("rpi64", "rpi", "psc", "pcusb", "windows", "win64", "win")
VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")
HEAD_BYTES = 64
INGEST_EVERY = 600   # seconds between the background reads
FRESH = 30           # an answer reads the log again when the last read is older than this

SCHEMA = """
CREATE TABLE IF NOT EXISTS counts (day TEXT NOT NULL, path TEXT NOT NULL, n INTEGER NOT NULL,
                                   PRIMARY KEY (day, path));
CREATE TABLE IF NOT EXISTS logs (inode INTEGER PRIMARY KEY, offset INTEGER NOT NULL,
                                 head_len INTEGER NOT NULL, head_sha TEXT NOT NULL);
"""


def parse_line(line):
    """(day, path) for a line that is one counted download, else None"""
    try:
        e = json.loads(line)
        req = e["request"]
        if req.get("method") != "GET" or e.get("status") != 200:
            return None
        path = unquote(urlsplit(req["uri"]).path).lstrip("/")
        day = datetime.fromtimestamp(float(e["ts"]), timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError):
        return None
    if not path.lower().endswith(DOWNLOAD_EXT) or path.startswith(SKIP_PREFIX) or ".." in path.split("/"):
        return None
    return day, path


def classify(path):
    """what the path itself says: the group (its top folder), the platform and the version, '' when it does not"""
    parts = path.split("/")
    name = re.sub(r"(\.tar)?\.[A-Za-z0-9]+$", "", parts[-1])
    platform = ""
    for token in [p.lower() for p in parts[:-1]] + re.split(r"[-_.]", name.lower()):
        if token in PLATFORMS:
            platform = {"win64": "windows", "win": "windows"}.get(token, token)
            break
    version = ""
    for part in reversed(parts[:-1] + [name]):
        m = VERSION_RE.search(part)
        if m:
            version = m.group(0)
            break
    return {"group": parts[0] if len(parts) > 1 else "(root)", "platform": platform, "version": version,
            "channel": channel_of(parts, version)}


def channel_of(parts, version):
    """release / testing / nightly / preview as far as the path tells ('' when it does not)"""
    folders = parts[:-1]
    if "preview" in folders:
        return "preview"
    if "nightly" in folders or re.search(r"-\d{8}-", version + "-"):
        return "nightly"
    if re.search(r"-(alpha|beta|rc|pre|test)", version, re.I):
        return "testing"
    return "release" if version else ""


class Downloads:
    def __init__(self, settings):
        self.db_path = os.path.join(settings.data_dir, "downloads.sqlite3")
        self.log_dir = settings.log_dir
        self.lock = threading.Lock()
        self.last_read = 0.0

    def _connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.executescript(SCHEMA)
        return db

    def _log_files(self):
        try:
            names = os.listdir(self.log_dir)
        except OSError:
            return []
        files = [os.path.join(self.log_dir, n) for n in names if n.startswith("access") and not n.endswith(".gz")]
        return sorted(files, key=lambda p: (os.stat(p).st_mtime, p))

    def ingest(self):
        """read what the access logs gained since the last read; returns the downloads added"""
        with self.lock:
            db = self._connect()
            try:
                added = 0
                seen = set()
                with db:
                    for path in self._log_files():
                        added += self._ingest_file(db, path, seen)
                    # a rotated file that Caddy has deleted leaves its state row behind: drop it
                    for (inode,) in db.execute("SELECT inode FROM logs").fetchall():
                        if inode not in seen:
                            db.execute("DELETE FROM logs WHERE inode=?", (inode,))
                self.last_read = time.time()
                return added
            finally:
                db.close()

    def _ingest_file(self, db, path, seen):
        try:
            f = open(path, "rb")
        except OSError:
            return 0
        with f:
            st = os.fstat(f.fileno())
            inode = st.st_ino
            seen.add(inode)
            row = db.execute("SELECT offset, head_len, head_sha FROM logs WHERE inode=?", (inode,)).fetchone()
            offset = 0
            if row:
                offset, head_len, head_sha = row
                head = f.read(head_len)
                # a reused inode (a new file) or a truncated one starts again from the top
                if st.st_size < offset or hashlib.sha1(head).hexdigest() != head_sha:
                    offset = 0
            f.seek(offset)
            data = f.read()
            end = data.rfind(b"\n")
            if end < 0:
                return 0
            data = data[:end + 1]
            counts = {}
            for line in data.splitlines():
                hit = parse_line(line)
                if hit:
                    counts[hit] = counts.get(hit, 0) + 1
            for (day, p), n in counts.items():
                db.execute("INSERT INTO counts (day, path, n) VALUES (?, ?, ?) "
                           "ON CONFLICT(day, path) DO UPDATE SET n = n + excluded.n", (day, p, n))
            f.seek(0)
            head = f.read(min(HEAD_BYTES, offset + len(data)))
            db.execute("INSERT OR REPLACE INTO logs (inode, offset, head_len, head_sha) VALUES (?, ?, ?, ?)",
                       (inode, offset + len(data), len(head), hashlib.sha1(head).hexdigest()))
            return sum(counts.values())

    def report(self, today=None, top=10):
        """totals, the last 7 and 30 days, and the same per file, per group, per platform and per version"""
        today = today or datetime.now(timezone.utc).date()
        d7 = (today - timedelta(days=6)).isoformat()
        d30 = (today - timedelta(days=29)).isoformat()
        db = self._connect()
        try:
            rows = db.execute("SELECT day, path, n FROM counts").fetchall()
        finally:
            db.close()
        files, by_day = {}, {}
        today_s = today.isoformat()
        for day, path, n in rows:
            f = files.setdefault(path, dict(path=path, total=0, today=0, last7=0, last30=0, **classify(path)))
            f["total"] += n
            if day == today_s:
                f["today"] += n
            if day >= d30:
                f["last30"] += n
                by_day[day] = by_day.get(day, 0) + n
                if day >= d7:
                    f["last7"] += n

        def fold(key):
            out = {}
            for f in files.values():
                g = out.setdefault(f[key] or "(not in the path)", dict(name=f[key] or "(not in the path)",
                                                                       total=0, today=0, last7=0, last30=0))
                for k in ("total", "today", "last7", "last30"):
                    g[k] += f[k]
            return sorted(out.values(), key=lambda g: (-g["total"], g["name"]))

        listing = sorted(files.values(), key=lambda f: (-f["total"], f["path"]))
        return {
            "since": min((r[0] for r in rows), default=None),
            "total": sum(f["total"] for f in listing),
            "today": sum(f["today"] for f in listing),
            "last7": sum(f["last7"] for f in listing),
            "last30": sum(f["last30"] for f in listing),
            "files": listing,
            # the summary's top: the busiest files of the last 7 days (a file with none in them is not in it)
            "top": [f for f in sorted(listing, key=lambda f: (-f["last7"], f["path"]))[:top] if f["last7"]],
            "groups": fold("group"), "platforms": fold("platform"), "channels": fold("channel"),
            "versions": fold("version"),
            "days": [{"day": (today - timedelta(days=i)).isoformat(),
                      "n": by_day.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(29, -1, -1)],
        }

    def fresh_report(self):
        """the report after a read of the log (skipped when one happened a moment ago)"""
        if time.time() - self.last_read > FRESH:
            self.ingest()
        return self.report()

    def start(self):
        """a background read every INGEST_EVERY seconds, so a rotated log is never missed"""

        def loop():
            while True:
                try:
                    self.ingest()
                except Exception:  # the panel must outlive a bad log
                    pass
                time.sleep(INGEST_EVERY)
        threading.Thread(target=loop, daemon=True, name="download-counter").start()
