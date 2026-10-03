"""The tester portal's data for the panel: what the intake service stored (intake/README.md is the contract) and the
site's test plans, read into the three tabs - Test results, Coverage, Reports - and the one thing the panel writes
there, `decisions/<id>.json`.

Everything is read on every request (the volume is small and the service is the only other writer); a missing
intake directory, a missing plan or a damaged file is "no data", never an error. Text from testers is passed on as
data: the page puts it in with textContent, and nothing here builds HTML.
"""
import glob
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import yaml

PLATFORM_ORDER = ("psc", "rpi", "pcusb", "win")  # the plans' platforms; any other folder name sorts after them
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")  # a platform or a version used as a folder name
ID_RE = re.compile(r"^[a-z0-9]{8}$")
BUG_RE = re.compile(r"^BUG-\d{1,6}$")
# the states the panel writes, and the word the intake service's /submit/status answers (the contract's list)
DECISIONS = {"to-reproduce": "to-reproduce", "not-a-bug": "not-a-bug", "idea": "idea", "needs-info": "needs-info"}
REASON_MAX = 200
DEFAULT_TARGET, DEFAULT_CLAIM_HOURS = 3, 48


def version_key(tag):
    """Port of tools/repo_index.py's version_key (the site's version order), without the publish-time tie-break:
    v2.0.0-alpha1 < v2.0.0-alpha2 < v2.0.0-rc1 < v2.0.0; a trailing commit hash is ignored."""
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-(.*))?$", tag)
    if not m:
        return (0, 0, 0, 0, (0, 0, 0, tag))
    major, minor, patch, suffix = m.groups()
    label = re.sub(r"-[0-9a-f]{7,40}$", "", suffix or "")
    ranks = {"pre": 0, "alpha": 1, "beta": 2, "rc": 3}
    lm = re.match(r"^(pre|alpha|beta|rc)(\d*)(?:\.(\d+))?$", label)  # alpha1.1: a point release of alpha1
    label_key = (ranks[lm.group(1)], int(lm.group(2) or 0), int(lm.group(3) or 0), "") if lm else (4, 0, 0, label)
    return (int(major), int(minor), int(patch or 0), 0 if suffix else 1, label_key)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dirs(path):
    try:
        return sorted(n for n in os.listdir(path) if os.path.isdir(os.path.join(path, n)))
    except OSError:
        return []


def _platform_sort(names):
    return sorted(set(names), key=lambda p: (PLATFORM_ORDER.index(p) if p in PLATFORM_ORDER else len(PLATFORM_ORDER), p))


def _parse_time(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Intake:
    def __init__(self, settings):
        self.dir = settings.intake_dir
        self.repo_dir = settings.repo_dir

    # ------------------------------------------------------------------------------------------ plans, settings
    def plan(self, platform, version):
        """the site's testplans/<version>/<platform>.yaml as a dict, or None"""
        path = os.path.join(self.repo_dir, "testplans", version, platform + ".yaml")
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("sections"), list) else None

    def settings(self):
        data = _load_json(os.path.join(self.dir, "settings.json")) or {}

        def number(key, default):
            v = data.get(key)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else default
        return {"target_passes": number("target_passes", DEFAULT_TARGET),
                "claim_hours": number("claim_hours", DEFAULT_CLAIM_HOURS)}

    # ------------------------------------------------------------------------------------------ versions
    def versions(self):
        """every version that has a plan or a stored result or claim, oldest first by the site's order"""
        found = set(n for n in _dirs(os.path.join(self.repo_dir, "testplans")) if NAME_RE.match(n))
        for kind in ("testplans", "claims"):
            for platform in _dirs(os.path.join(self.dir, kind)):
                found.update(n for n in _dirs(os.path.join(self.dir, kind, platform)) if NAME_RE.match(n))
        return sorted(found, key=version_key)

    def pick_version(self, wanted):
        """(version, versions): the wanted one, else the current = the highest; version None when there is none"""
        versions = self.versions()
        if wanted:
            return (wanted if NAME_RE.match(wanted) else None), versions
        return (versions[-1] if versions else None), versions

    def platforms(self, version):
        names = [n[:-5] for n in self._plan_files(version)]
        for kind in ("testplans", "claims"):
            for platform in _dirs(os.path.join(self.dir, kind)):
                if os.path.isdir(os.path.join(self.dir, kind, platform, version)):
                    names.append(platform)
        return _platform_sort(n for n in names if NAME_RE.match(n))

    def _plan_files(self, version):
        try:
            return [n for n in os.listdir(os.path.join(self.repo_dir, "testplans", version)) if n.endswith(".yaml")]
        except OSError:
            return []

    # ------------------------------------------------------------------------------------------ results, claims
    def results(self, platform, version):
        """the stored results of a platform and version, oldest first; each dict gets `id` and `file`"""
        folder = os.path.join(self.dir, "testplans", platform, version)
        out = []
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
        except OSError:
            return out
        for name in names:
            data = _load_json(os.path.join(folder, name))
            if data is None:
                continue
            data["id"] = name[:-5].rsplit("-", 1)[-1]
            data["file"] = name
            out.append(data)
        return out

    def claims(self, platform, version):
        folder = os.path.join(self.dir, "claims", platform, version)
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
        except OSError:
            return []
        return [c for c in (_load_json(os.path.join(folder, n)) for n in names) if c]

    def raw_result(self, platform, version, result_id):
        """the path of a stored result's file, None when there is none (the names are checked: no folder escapes)"""
        if not (NAME_RE.match(platform) and NAME_RE.match(version) and ID_RE.match(result_id)):
            return None
        hits = glob.glob(os.path.join(glob.escape(self.dir), "testplans", platform, version, "*-%s.json" % result_id))
        return hits[0] if hits else None

    # ------------------------------------------------------------------------------------------ Test results tab
    def test_results(self, wanted_version):
        version, versions = self.pick_version(wanted_version)
        out = {"version": version, "versions": versions, "platforms": []}
        if version is None:
            return out
        for platform in self.platforms(version):
            plan = self.plan(platform, version)
            results = self.results(platform, version)
            out["platforms"].append({"platform": platform, "title": (plan or {}).get("title", platform),
                                     "count": len(results), "sections": self._matrix(plan, results),
                                     "results": [{"id": r["id"], "file": r["file"], "received": r.get("received", ""),
                                                  "section": r.get("section", ""), "device": r.get("device", ""),
                                                  "unassigned": bool(r.get("unassigned"))} for r in results]})
        return out

    @staticmethod
    def _matrix(plan, results):
        """the plan's sections and steps in plan order with the counts; steps or sections a result names that the
        plan does not (or no plan at all) follow, in the order they appear"""
        sections, by_step = [], {}

        def section_of(sid, title):
            for s in sections:
                if s["id"] == sid:
                    return s
            s = {"id": sid, "title": title or sid, "steps": []}
            sections.append(s)
            return s

        def step_of(section, stid, do):
            step = by_step.get(stid)
            if step is None:
                step = {"id": stid, "do": do or "", "ok": 0, "problem": 0, "na": 0, "problems": []}
                section["steps"].append(step)
                by_step[stid] = step
            return step
        for s in (plan or {}).get("sections", []):
            if isinstance(s, dict):
                sec = section_of(str(s.get("id", "")), s.get("title"))
                for st in s.get("steps") or []:
                    if isinstance(st, dict):
                        step_of(sec, str(st.get("id", "")), st.get("do"))
        for r in results:
            sec = section_of(str(r.get("section", "")), None)
            for a in r.get("steps") or []:
                if not isinstance(a, dict) or a.get("status") not in ("ok", "problem", "na"):
                    continue
                step = step_of(sec, str(a.get("id", "")), "")
                step[a["status"]] += 1
                if a["status"] == "problem":
                    step["problems"].append({"result": r["id"], "comment": str(a.get("comment", "")),
                                             "device": str(r.get("device", ""))})
        return sections

    # ------------------------------------------------------------------------------------------ Coverage tab
    def coverage(self, wanted_version):
        version, versions = self.pick_version(wanted_version)
        cfg = self.settings()
        out = {"version": version, "versions": versions, "target": cfg["target_passes"],
               "claim_hours": cfg["claim_hours"], "platforms": [], "sections": []}
        if version is None:
            return out
        out["platforms"] = self.platforms(version)
        rows, cells = [], {}
        now = datetime.now(timezone.utc)
        for platform in out["platforms"]:
            plan = self.plan(platform, version)
            for s in (plan or {}).get("sections", []):
                if isinstance(s, dict) and str(s.get("id", "")) not in cells:
                    rows.append(str(s["id"]))
                    cells[str(s["id"])] = {"title": s.get("title") or str(s["id"]), "cells": {}}
                if isinstance(s, dict):
                    cells[str(s["id"])]["cells"][platform] = {"passes": 0, "problems": 0, "open": 0, "expired": 0}
            for r in self.results(platform, version):
                cell = self._cell(cells, rows, platform, r.get("section"))
                cell["passes"] += 1
                if any(isinstance(a, dict) and a.get("status") == "problem" for a in r.get("steps") or []):
                    cell["problems"] += 1
            for c in self.claims(platform, version):
                if c.get("closed_by"):
                    continue
                made = _parse_time(c.get("made"))
                section = c.get("section")
                section = section.get("id") if isinstance(section, dict) else section
                cell = self._cell(cells, rows, platform, section)
                if made is not None and now >= made + timedelta(hours=cfg["claim_hours"]):
                    cell["expired"] += 1
                else:
                    cell["open"] += 1
        out["sections"] = [{"id": sid, "title": cells[sid]["title"], "cells": cells[sid]["cells"]} for sid in rows]
        return out

    @staticmethod
    def _cell(cells, rows, platform, section):
        sid = str(section or "")
        if sid not in cells:
            rows.append(sid)
            cells[sid] = {"title": sid, "cells": {}}
        return cells[sid]["cells"].setdefault(platform, {"passes": 0, "problems": 0, "open": 0, "expired": 0})

    # ------------------------------------------------------------------------------------------ Reports tab
    def decision(self, report_id):
        data = _load_json(os.path.join(self.dir, "decisions", report_id + ".json")) if ID_RE.match(report_id) else None
        return data or {}

    def _entry(self, kind, rid, received, platform, version, fields, has_logs):
        d = self.decision(rid)
        return {"id": rid, "kind": kind, "received": received, "platform": platform, "version": version,
                "fields": fields, "has_logs": has_logs, "state": d.get("state") or "received",
                "reason": d.get("reason", ""), "bug": d.get("bug", ""), "by": d.get("by", ""),
                "decided": d.get("at", "")}

    def reports(self):
        """every issue report and every test result with a problem, newest first"""
        items = []
        for day in _dirs(os.path.join(self.dir, "issues")):
            for rid in _dirs(os.path.join(self.dir, "issues", day)):
                folder = os.path.join(self.dir, "issues", day, rid)
                data = _load_json(os.path.join(folder, "report.json"))
                if data is None or not ID_RE.match(rid):
                    continue
                items.append(self._entry("issue", rid, str(data.get("received", day)), str(data.get("platform", "")),
                                         str(data.get("version", "")), data,
                                         os.path.isfile(os.path.join(folder, "logs.zip"))))
        for platform in _dirs(os.path.join(self.dir, "testplans")):
            for version in _dirs(os.path.join(self.dir, "testplans", platform)):
                for r in self.results(platform, version):
                    bad = [a for a in r.get("steps") or [] if isinstance(a, dict) and a.get("status") == "problem"]
                    if not bad:
                        continue
                    fields = {k: r[k] for k in ("section", "device", "contact", "unassigned") if k in r}
                    fields["problems"] = [{"id": a.get("id", ""), "comment": a.get("comment", "")} for a in bad]
                    items.append(self._entry("testresult", r["id"], str(r.get("received", "")), platform, version,
                                             fields, False))
        items.sort(key=lambda i: i["received"], reverse=True)
        return items

    def logs_path(self, report_id):
        if not ID_RE.match(report_id):
            return None
        hits = glob.glob(os.path.join(glob.escape(self.dir), "issues", "*", report_id, "logs.zip"))
        return hits[0] if hits else None

    def known(self, report_id):
        """whether an issue or a stored result has this id (a decision is only ever written for one)"""
        if not ID_RE.match(report_id):
            return False
        if glob.glob(os.path.join(glob.escape(self.dir), "issues", "*", report_id, "report.json")):
            return True
        return bool(glob.glob(os.path.join(glob.escape(self.dir), "testplans", "*", "*", "*-%s.json" % report_id)))

    def decide(self, report_id, state, who, reason="", bug=""):
        """write decisions/<id>.json atomically; ValueError for anything the contract does not allow. Returns the
        text for the audit log."""
        reason, bug = (reason or "").strip(), (bug or "").strip().upper()
        if not self.known(report_id):
            raise ValueError("no such report: %s" % report_id)
        data = {}
        if state == "bug":
            if not BUG_RE.match(bug):
                raise ValueError("record as bug needs a BUG-N number")
            data["state"], data["bug"] = "bug %s" % bug, bug
        elif state in DECISIONS:
            data["state"] = DECISIONS[state]
        else:
            raise ValueError("state is one of: to-reproduce, not-a-bug, idea, needs-info, bug")
        if state == "not-a-bug" and not reason:
            raise ValueError("not a bug needs a short reason")
        if len(reason) > REASON_MAX:
            raise ValueError("the reason is at most %d characters" % REASON_MAX)
        if reason:
            data["reason"] = reason
        data["by"], data["at"] = who, _now_iso()
        folder = os.path.join(self.dir, "decisions")
        if not os.path.isdir(folder):   # normally made by intake at its start; the shared group's modes
            os.makedirs(folder, exist_ok=True)
            os.chmod(folder, 0o2770)
        tmp = os.path.join(folder, ".%s.%d.tmp" % (report_id, os.getpid()))
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o640)   # group-readable: intake's /submit/status reads it
        os.replace(tmp, os.path.join(folder, report_id + ".json"))
        return "%s is now %s" % (report_id, data["state"])
