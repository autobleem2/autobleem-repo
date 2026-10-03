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
# a preview's folder (autobleem-appliance's assemble.yml: preview-<branch slug>-<fingerprint>) and the branch
# a preview is built from (autobleem-main's release.py PREVIEW_BRANCH)
PREVIEW_VERSION_RE = re.compile(r"^preview-[a-z0-9.-]+$")
BRANCH_RE = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")

# keep in step with autobleem-main's tools/release.py (next_tag): the tag a promotion makes
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc|pre)\.?(\d+)(?:\.(\d+))?)?$")
RANKS = {"pre": 0, "alpha": 1, "beta": 2, "rc": 3}


def next_tag(tags, kind, version=None, point=False):
    """the tag a promotion makes; `point`: the next point of the current pre-release (alpha1 -> alpha1.1), see
    release.py - a point sorts above its number and below the next one (alpha1 < alpha1.1 < alpha2)"""
    parsed = [m for m in (TAG_RE.match(t) for t in tags) if m]
    parsed = [((int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4), int(m.group(5) or 0),
               int(m.group(6) or 0)) for m in parsed]
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
        if point:
            raise ValueError("a release has no point version - a point is of a pre-release")
        return name
    if point:
        current = max([p for p in parsed if p[0] == base and p[1] is not None],
                      key=lambda p: (RANKS[p[1]], p[2], p[3]), default=None)
        if not current or current[1] != kind:
            raise ValueError("no %s in progress for %s - a point release follows the newest pre-release"
                             % (kind, name))
        return "%s-%s%d.%d" % (name, kind, current[2], current[3] + 1)
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

    def preview_build(self, branch, platforms, dry_run=False):
        """PLATFORM-20: a feature branch built into preview/<version>/ (autobleem-main's preview.yml)"""
        branch = (branch or "").strip()
        if not BRANCH_RE.match(branch) or branch in ("develop", "master", "main"):
            raise ValueError("a feature branch, e.g. feature/ab-gui")
        chosen = [p for p in platforms if p in PLATFORMS] or list(PLATFORMS)
        self._dispatch("autobleem-main", "preview.yml", {
            "branch": branch, "platforms": " ".join(chosen), "dry_run": bool(dry_run)})
        return "preview of %s started%s" % (branch, " (dry run)" if dry_run else "")

    def preview(self, kind, version=None, point=False):
        if kind not in KINDS:
            raise ValueError("kind is one of " + ", ".join(KINDS))
        tags = self.gh.call("GET", "/repos/%s/autobleem/tags?per_page=100" % self.settings.org)
        return next_tag([t["name"] for t in tags], kind, version or None, point)

    def promote(self, kind, version=None, dry_run=True, point=False):
        tag = self.preview(kind, version, point)  # fails before anything starts when the version makes no sense
        self._dispatch("autobleem-main", "promote.yml",
                       {"kind": kind, "version": version or "", "point": bool(point), "dry_run": bool(dry_run)})
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
        ok = PREVIEW_VERSION_RE if kind == "preview" else VERSION_RE
        if kind not in ("nightly", "testing", "preview") or not ok.match(version or ""):
            raise ValueError("a nightly, testing or preview build, by its version")
        if kind == "testing" and "-" not in version:
            raise ValueError("a stable release is not withdrawn from here")
        return self._dispatch("autobleem-repo", "withdraw.yml",
                              {"kind": kind, "version": version, "restore": bool(restore)})

    def page(self):
        return self._dispatch("autobleem-repo", "page.yml", {})

    def _check_repo(self, repo):
        if repo not in self.settings.repos:
            raise ValueError("not a repository the panel manages: %s" % repo)
