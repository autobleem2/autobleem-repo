"""What the release team can do - each one starts a workflow (the logic lives there, docs/archive/admin-panel-plan.md)
or cancels / re-runs a run - and the audit log every action lands in."""
import json
import os
import re
import threading
import time

PLATFORMS = ("rpi-armhf", "rpi-arm64", "pcusb", "psc", "win")
KINDS = ("alpha", "beta", "rc", "release")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$")

# keep in step with autobleem-main's tools/release.py (next_tag): the tag a promotion makes
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc|pre)\.?(\d+))?$")


def next_tag(tags, kind, version=None):
    parsed = [m for m in (TAG_RE.match(t) for t in tags) if m]
    parsed = [((int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4), int(m.group(5) or 0))
              for m in parsed]
    released = {p[0] for p in parsed if p[1] is None}
    if version:
        m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", version)
        if not m:
            raise ValueError("version must be X.Y.Z")
        base = tuple(int(x) for x in m.groups())
    else:
        open_bases = sorted({p[0] for p in parsed if p[1] is not None and p[0] not in released})
        if not open_bases:
            raise ValueError("no pre-release in progress - give the version X.Y.Z")
        base = open_bases[-1]
    if base in released:
        raise ValueError("v%d.%d.%d is released already" % base)
    name = "v%d.%d.%d" % base
    if kind == "release":
        return name
    return "%s-%s%d" % (name, kind, max([p[2] for p in parsed if p[0] == base and p[1] == kind] or [0]) + 1)


class Audit:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "audit.jsonl")
        self.lock = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)

    def add(self, user, via, action, params, result):
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "user": user, "via": via,
                 "action": action, "params": params, "result": result}
        with self.lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def recent(self, n=100):
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()[-n:]
        except OSError:
            return []
        return [json.loads(l) for l in reversed(lines) if l.strip()]


class Actions:
    def __init__(self, gh, settings):
        self.gh, self.settings = gh, settings

    def _dispatch(self, repo, workflow, inputs):
        self.gh.call("POST", "/repos/%s/%s/actions/workflows/%s/dispatches" % (self.settings.org, repo, workflow),
                     {"ref": "develop", "inputs": inputs})
        return "started %s/%s" % (repo, workflow)

    def nightly(self, platforms, rebuild_all=False, dry_run=False):
        chosen = [p for p in platforms if p in PLATFORMS] or list(PLATFORMS)
        return self._dispatch("autobleem-main", "nightly.yml", {
            "platforms": " ".join(chosen), "rebuild_all": bool(rebuild_all), "dry_run": bool(dry_run)})

    def preview(self, kind, version=None):
        if kind not in KINDS:
            raise ValueError("kind is one of " + ", ".join(KINDS))
        tags = self.gh.call("GET", "/repos/%s/autobleem/tags?per_page=100" % self.settings.org)
        return next_tag([t["name"] for t in tags], kind, version or None)

    def promote(self, kind, version=None, dry_run=True):
        tag = self.preview(kind, version)  # fails before anything starts when the version makes no sense
        self._dispatch("autobleem-main", "promote.yml",
                       {"kind": kind, "version": version or "", "dry_run": bool(dry_run)})
        return "promotion to %s%s started" % (tag, " (dry run)" if dry_run else "")

    def cancel(self, repo, run_id):
        self._check_repo(repo)
        self.gh.call("POST", "/repos/%s/%s/actions/runs/%d/cancel" % (self.settings.org, repo, int(run_id)))
        return "cancelled %s run %s" % (repo, run_id)

    def rerun(self, repo, run_id, failed_only=True):
        self._check_repo(repo)
        what = "rerun-failed-jobs" if failed_only else "rerun"
        self.gh.call("POST", "/repos/%s/%s/actions/runs/%d/%s" % (self.settings.org, repo, int(run_id), what))
        return "re-ran %s run %s" % (repo, run_id)

    def withdraw(self, kind, version, restore=False):
        if kind not in ("nightly", "testing") or not VERSION_RE.match(version or ""):
            raise ValueError("a nightly or testing build, by its version")
        if kind == "testing" and "-" not in version:
            raise ValueError("a stable release is not withdrawn from here")
        return self._dispatch("autobleem-repo", "withdraw.yml",
                              {"kind": kind, "version": version, "restore": bool(restore)})

    def page(self):
        return self._dispatch("autobleem-repo", "page.yml", {})

    def _check_repo(self, repo):
        if repo not in self.settings.repos:
            raise ValueError("not a repository the panel manages: %s" % repo)
