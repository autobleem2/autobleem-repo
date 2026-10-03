"""Fake tester-portal data in the shape intake/README.md fixes: test plans for a site tree, and an intake data
directory with results, claims, issue reports and settings. Shared by the tests and tools/dev_server.py."""
import json
import os
from datetime import datetime, timedelta, timezone

import yaml


def _plan(platform, title, version, sections):
    return {"id": platform, "title": title, "version": version, "before_you_start": ["Get the zip."],
            "sections": [{"id": sid, "title": stitle, "minutes": 10, "needs": "A device.",
                          "steps": [{"id": "%s.%d" % (sid, i + 1), "do": "Do %s step %d" % (sid, i + 1),
                                     "expect": "It works.", "status": "", "comment": ""} for i in range(n)]}
                         for sid, stitle, n in sections]}


def write_plans(repo_dir):
    """testplans/<version>/<platform>.yaml for two versions (the older one has a psc plan only)"""
    plans = {
        ("v2.0.0-alpha1", "psc"): _plan("psc", "PlayStation Classic", "v2.0.0-alpha1",
                                        [("psc-install", "Install and first boot", 2), ("psc-store", "The Store", 2)]),
        ("v2.0.0-alpha1", "rpi"): _plan("rpi", "Raspberry Pi", "v2.0.0-alpha1", [("rpi-install", "Write the card", 2)]),
        ("v2.0.0-alpha0", "psc"): _plan("psc", "PlayStation Classic", "v2.0.0-alpha0", [("psc-install", "Install", 1)]),
    }
    for (version, platform), plan in plans.items():
        folder = os.path.join(repo_dir, "testplans", version)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, platform + ".yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(plan, f)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def result(rid, platform, version, section, statuses, received, comments=None, **extra):
    steps = [{"id": "%s.%d" % (section, i + 1), "status": s, "comment": (comments or {}).get(i, "")}
             for i, s in enumerate(statuses)]
    body = {"platform": platform, "version": version, "section": section, "claim": "c-" + rid, "steps": steps,
            "received": received}
    body.update(extra)
    return rid, body


def write_intake(root, now=None):
    """results (psc-install x2 with one problem, psc-store x1, rpi-install x3), claims (open, expired, closed),
    an issue with logs, an issue without, a hostile-text issue, settings"""
    now = now or datetime.now(timezone.utc)
    v = "v2.0.0-alpha1"
    results = [
        result("aaaa1111", "psc", v, "psc-install", ["ok", "ok"], "2026-10-02T09:00:00Z", device="PSC one"),
        result("aaaa2222", "psc", v, "psc-install", ["ok", "problem"], "2026-10-02T10:00:00Z",
               {1: "<script>alert(1)</script> hangs"}, device="PSC two"),
        result("bbbb1111", "psc", v, "psc-store", ["na", "ok"], "2026-10-02T11:00:00Z", unassigned=True),
        result("cccc1111", "rpi", v, "rpi-install", ["ok", "ok"], "2026-10-02T12:00:00Z"),
        result("cccc2222", "rpi", v, "rpi-install", ["ok", "ok"], "2026-10-02T13:00:00Z"),
        result("cccc3333", "rpi", v, "rpi-install", ["ok", "ok"], "2026-10-02T14:00:00Z"),
    ]
    for rid, body in results:
        stamp = body["received"].replace("-", "").replace(":", "")
        name = "%sT%s-%s.json" % (body["received"][:10], stamp[9:15], rid)
        _write(os.path.join(root, "testplans", body["platform"], v, name), body)
    # a result of the older version, so the version picker has two with results
    _write(os.path.join(root, "testplans", "psc", "v2.0.0-alpha0", "2026-09-01T080000-dddd1111.json"),
           {"platform": "psc", "version": "v2.0.0-alpha0", "section": "psc-install",
            "steps": [{"id": "psc-install.1", "status": "ok", "comment": ""}], "received": "2026-09-01T08:00:00Z"})
    _write(os.path.join(root, "testplans", "psc", v, "broken.json"), "{not json")
    claims = [("open1", "psc-install", now - timedelta(hours=2), None),
              ("old1", "psc-install", now - timedelta(hours=100), None),
              ("done1", "psc-store", now - timedelta(hours=1), "bbbb1111"),
              ("rel1", "psc-store", now - timedelta(hours=1), "released")]
    for cid, section, made, closed in claims:
        _write(os.path.join(root, "claims", "psc", v, cid + ".json"),
               {"claim": cid, "section": section, "made": iso(made), "expires": iso(made + timedelta(hours=48)),
                "closed_by": closed})
    _write(os.path.join(root, "issues", "2026-10-02", "iiii1111", "report.json"),
           {"platform": "psc", "version": v, "steps": "Boot it", "expected": "A menu", "actual": "Black screen",
            "contact": "me@example.org", "received": "2026-10-02T15:00:00Z", "has_logs": True})
    _write(os.path.join(root, "issues", "2026-10-02", "iiii1111", "logs.zip"), "PK-fake-zip")
    _write(os.path.join(root, "issues", "2026-10-03", "iiii2222", "report.json"),
           {"platform": "rpi", "version": v, "steps": "<b>bold</b> & \"quotes\"", "expected": "x", "actual": "y",
            "received": "2026-10-03T08:00:00Z", "has_logs": False})
    _write(os.path.join(root, "settings.json"), {"target_passes": 2, "claim_hours": 48})
