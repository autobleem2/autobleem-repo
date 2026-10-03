"""The tester portal tabs (Test results, Coverage, Reports) over fake intake data in a temp dir.

    cd admin && python -m pytest -q
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ["AB_ADMIN_NO_APP"] = "1"
from app import main  # noqa: E402
from app.config import Settings  # noqa: E402
from app.testers import Intake, version_key  # noqa: E402
from tests.intake_data import write_intake, write_plans  # noqa: E402
from tests.test_admin import FakeGitHub, browser  # noqa: E402

V = "v2.0.0-alpha1"


def make(tmp_path, with_intake=True):
    repo, intake = tmp_path / "site", tmp_path / "intake"
    write_plans(str(repo))
    if with_intake:
        write_intake(str(intake))
    settings = Settings(repo_dir=str(repo), data_dir=str(tmp_path / "data"), intake_dir=str(intake), repos=["autobleem"])
    client = TestClient(main.create_app(settings, gh=FakeGitHub(), start_notifier=False))
    return client, intake


@pytest.fixture
def setup(tmp_path):
    return make(tmp_path)


def get(client, path, user="bob"):
    return client.get("/admin/api/" + path, headers=browser(user))


def test_version_order_is_the_sites():
    tags = ["v2.0.0", "v2.0.0-rc1", "v2.0.0-alpha10", "v2.0.0-alpha2", "v1.9.9", "v2.0.0-beta1"]
    assert sorted(tags, key=version_key) == ["v1.9.9", "v2.0.0-alpha2", "v2.0.0-alpha10", "v2.0.0-beta1",
                                              "v2.0.0-rc1", "v2.0.0"]


def test_version_order_puts_a_point_release_between_its_number_and_the_next():
    tags = ["v2.0.0-alpha2", "v2.0.0-alpha1.10", "v2.0.0-alpha1.2", "v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-beta1"]
    assert sorted(tags, key=version_key) == ["v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-alpha1.2",
                                              "v2.0.0-alpha1.10", "v2.0.0-alpha2", "v2.0.0-beta1"]


def test_version_default_is_the_highest(setup):
    client, _ = setup
    d = get(client, "testresults").json()
    assert d["version"] == V
    assert d["versions"] == ["v2.0.0-alpha0", V]
    assert get(client, "testresults?version=v2.0.0-alpha0").json()["version"] == "v2.0.0-alpha0"
    assert get(client, "coverage").json()["version"] == V


def test_results_matrix_counts_and_problems(setup):
    client, _ = setup
    d = get(client, "testresults").json()
    assert [p["platform"] for p in d["platforms"]] == ["psc", "rpi"]
    psc = d["platforms"][0]
    assert psc["count"] == 3 and psc["title"] == "PlayStation Classic"  # the broken file is skipped
    assert [s["id"] for s in psc["sections"]] == ["psc-install", "psc-store"]  # plan order
    steps = {st["id"]: st for s in psc["sections"] for st in s["steps"]}
    assert (steps["psc-install.1"]["ok"], steps["psc-install.1"]["problem"], steps["psc-install.1"]["na"]) == (2, 0, 0)
    assert (steps["psc-install.2"]["ok"], steps["psc-install.2"]["problem"]) == (1, 1)
    assert steps["psc-store.1"]["na"] == 1 and steps["psc-store.2"]["ok"] == 1
    assert steps["psc-install.2"]["problems"] == [
        {"result": "aaaa2222", "comment": "<script>alert(1)</script> hangs", "device": "PSC two"}]
    assert steps["psc-install.1"]["do"] == "Do psc-install step 1"
    assert {r["id"] for r in psc["results"]} == {"aaaa1111", "aaaa2222", "bbbb1111"}


def test_raw_result_download(setup):
    client, _ = setup
    r = get(client, "testresults/psc/%s/aaaa2222" % V)
    assert r.status_code == 200 and r.json()["section"] == "psc-install"
    assert "attachment" in r.headers["content-disposition"]
    assert get(client, "testresults/psc/%s/zzzz9999" % V).status_code == 404
    assert get(client, "testresults/psc/%s/..%%2f..%%2fsettings" % V).status_code == 404
    assert get(client, "testresults/..%%2f..%%2f/%s/aaaa2222" % V).status_code in (404, 400)


def test_coverage_cells_and_claims(setup):
    client, _ = setup
    d = get(client, "coverage").json()
    assert d["target"] == 2 and d["claim_hours"] == 48 and d["platforms"] == ["psc", "rpi"]
    rows = {s["id"]: s["cells"] for s in d["sections"]}
    assert rows["psc-install"]["psc"] == {"passes": 2, "problems": 1, "open": 1, "expired": 1}
    assert rows["psc-store"]["psc"] == {"passes": 1, "problems": 0, "open": 0, "expired": 0}  # closed claims not counted
    assert rows["rpi-install"]["rpi"]["passes"] == 3 and "psc" not in rows["rpi-install"]


def test_coverage_defaults_without_settings_file(setup):
    client, intake = setup
    os.remove(os.path.join(str(intake), "settings.json"))
    d = get(client, "coverage").json()
    assert d["target"] == 3 and d["claim_hours"] == 48


def test_claim_hours_from_settings(setup):
    client, intake = setup
    (intake / "settings.json").write_text(json.dumps({"target_passes": 3, "claim_hours": 1000}))
    cell = {s["id"]: s["cells"] for s in get(client, "coverage").json()["sections"]}["psc-install"]["psc"]
    assert (cell["open"], cell["expired"]) == (2, 0)


def test_reports_list_newest_first_with_states(setup):
    client, intake = setup
    items = get(client, "reports").json()["reports"]
    assert [i["id"] for i in items] == ["iiii2222", "iiii1111", "aaaa2222"]  # issues + the one result with a problem
    assert [i["kind"] for i in items] == ["issue", "issue", "testresult"]
    assert all(i["state"] == "received" for i in items)
    assert items[1]["has_logs"] and not items[0]["has_logs"]
    assert items[2]["fields"]["problems"] == [{"id": "psc-install.2", "comment": "<script>alert(1)</script> hangs"}]
    assert items[0]["fields"]["steps"] == "<b>bold</b> & \"quotes\""  # data as written; the page sets text nodes
    os.makedirs(str(intake / "decisions"))
    (intake / "decisions" / "iiii1111.json").write_text(json.dumps(
        {"state": "needs-info", "by": "alice", "at": "2026-10-03T01:00:00Z"}))
    again = {i["id"]: i for i in get(client, "reports").json()["reports"]}
    assert again["iiii1111"]["state"] == "needs-info" and again["iiii1111"]["by"] == "alice"


def test_log_download(setup):
    client, _ = setup
    r = get(client, "reports/iiii1111/logs")
    assert r.status_code == 200 and r.content == b"PK-fake-zip" and r.headers["content-type"] == "application/zip"
    assert get(client, "reports/iiii2222/logs").status_code == 404
    assert client.get("/admin/api/reports/iiii1111/logs").status_code == 401
    assert get(client, "reports/iiii1111/logs", "eve").status_code == 403  # not an org member


def decide(client, rid, body, user="alice"):
    return client.post("/admin/api/reports/%s/decision" % rid, json=body, headers=browser(user, act=True))


def test_decisions_write_atomically_and_audit(setup):
    client, intake = setup
    r = decide(client, "iiii1111", {"state": "to-reproduce"})
    assert r.status_code == 200
    d = json.loads((intake / "decisions" / "iiii1111.json").read_text())
    assert d["state"] == "to-reproduce" and d["by"] == "alice" and d["at"].endswith("Z") and "reason" not in d
    assert decide(client, "iiii1111", {"state": "not-a-bug", "reason": "works as designed"}).status_code == 200
    d = json.loads((intake / "decisions" / "iiii1111.json").read_text())
    assert d == {"state": "not-a-bug", "reason": "works as designed", "by": "alice", "at": d["at"]}
    assert decide(client, "aaaa2222", {"state": "idea"}).status_code == 200  # a test result with a problem
    assert decide(client, "iiii2222", {"state": "needs-info"}).status_code == 200
    assert decide(client, "iiii2222", {"state": "bug", "bug": "bug-17"}).status_code == 200
    d = json.loads((intake / "decisions" / "iiii2222.json").read_text())
    assert d["state"] == "bug BUG-17" and d["bug"] == "BUG-17"
    assert sorted(os.listdir(str(intake / "decisions"))) == ["aaaa2222.json", "iiii1111.json", "iiii2222.json"]  # no temp left
    audit = get(client, "audit", "alice").json()
    entries = [e for e in audit if e["action"] == "report-decision"]
    assert len(entries) == 5 and entries[0]["user"] == "alice" and entries[0]["params"]["id"] == "iiii2222"
    assert get(client, "reports").json()["reports"][0]["state"] == "bug BUG-17"


def test_decision_refusals_are_audited_and_write_nothing(setup):
    client, intake = setup
    assert decide(client, "iiii1111", {"state": "not-a-bug"}).status_code == 400  # a reason is needed
    assert decide(client, "iiii1111", {"state": "bug", "bug": "17"}).status_code == 400
    assert decide(client, "iiii1111", {"state": "bug"}).status_code == 400
    assert decide(client, "iiii1111", {"state": "approved"}).status_code == 400
    assert decide(client, "iiii1111", {"state": "idea", "reason": "x" * 201}).status_code == 400
    assert decide(client, "nope0000", {"state": "idea"}).status_code == 404
    assert decide(client, "..%2f..%2fx", {"state": "idea"}).status_code == 404
    assert not (intake / "decisions").exists()
    refused = [e for e in get(client, "audit", "alice").json() if str(e["result"]).startswith("refused")]
    assert len(refused) == 5


def test_a_member_may_look_but_not_decide(setup):
    client, intake = setup
    assert decide(client, "iiii1111", {"state": "idea"}, "bob").status_code == 403
    assert decide(client, "iiii1111", {"state": "idea"}, "eve").status_code == 403
    r = client.post("/admin/api/reports/iiii1111/decision", json={"state": "idea"}, headers=browser("alice"))
    assert r.status_code == 403  # a browser without X-AB-Request
    assert client.post("/admin/api/reports/iiii1111/decision", json={"state": "idea"}).status_code == 401
    assert not (intake / "decisions").exists()
    for path in ("testresults", "coverage", "reports"):
        assert get(client, path, "bob").status_code == 200


def test_text_is_returned_as_json_never_html(setup):
    client, _ = setup
    for path in ("testresults", "coverage", "reports"):
        assert get(client, path).headers["content-type"].startswith("application/json")
    page = client.get("/admin/", headers=browser("bob")).text
    start = page.index("tester portal tabs")
    code = page[start:page.index("// ----", start + 10)]
    assert "innerHTML" not in code and "insertAdjacent" not in code


def test_missing_intake_dir_is_no_data(tmp_path):
    client, _ = make(tmp_path, with_intake=False)
    d = get(client, "testresults").json()
    assert d["version"] == V and [p["platform"] for p in d["platforms"]] == ["psc", "rpi"]
    assert all(p["count"] == 0 for p in d["platforms"])
    cov = get(client, "coverage").json()
    assert cov["target"] == 3 and all(c["passes"] == 0 for s in cov["sections"] for c in s["cells"].values())
    assert get(client, "reports").json() == {"reports": []}
    assert get(client, "reports/iiii1111/logs").status_code == 404
    assert decide(client, "iiii1111", {"state": "idea"}).status_code == 404


def test_no_plans_and_no_intake_at_all(tmp_path):
    settings = Settings(repo_dir=str(tmp_path / "none"), data_dir=str(tmp_path / "data"),
                        intake_dir=str(tmp_path / "nothing"), repos=["autobleem"])
    client = TestClient(main.create_app(settings, gh=FakeGitHub(), start_notifier=False))
    assert get(client, "testresults").json() == {"version": None, "versions": [], "platforms": []}
    assert get(client, "coverage").json()["sections"] == []
    assert Intake(settings).reports() == []
