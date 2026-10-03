"""The intake service: claims, results, issues, limits, status (the contract: intake/README.md).

    cd intake && python -m pytest -q
"""
import glob
import io
import json
import os
import zipfile

from conftest import PSC_STEPS, VERSION, answers, result, take


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def issue_form(**extra):
    form = {"platform": "psc", "version": VERSION, "steps": "1. open it", "expected": "it opens",
            "actual": "it crashes"}
    form.update(extra)
    return form


def post_issue(client, form=None, logs=None, name="logs.zip"):
    files = {"logs": (name, logs, "application/zip")} if logs is not None else None
    return client.post("/submit/issue", data=form or issue_form(), files=files)


def files_under(data):
    return [os.path.join(d, f) for d, _, fs in os.walk(data) for f in fs]


# ---- claims

def test_claim_takes_the_first_section_when_nothing_is_done(client):
    c = take(client)
    assert c["section"]["id"] == "psc-install"
    assert set(c["section"]) == {"id", "title", "minutes", "needs"}
    assert c["expires"] == "2026-10-05T12:00:00Z"
    assert len(c["claim"]) == 16


def test_claim_goes_to_the_section_with_fewest_passes(client):
    client.post("/submit/testplan", json=result("psc-install"))
    assert take(client)["section"]["id"] == "psc-launcher"


def test_tie_on_passes_goes_to_fewest_open_claims_then_plan_order(client):
    # install has one pass, launcher and store none; open claims then break the tie between them
    client.post("/submit/testplan", json=result("psc-install"))
    assert take(client)["section"]["id"] == "psc-launcher"
    assert take(client)["section"]["id"] == "psc-store"      # launcher now has an open claim
    assert take(client)["section"]["id"] == "psc-launcher"   # both claimed once: plan order
    assert take(client)["section"]["id"] == "psc-store"


def test_same_claim_returns_the_same_section(client):
    c = take(client)
    again = take(client, claim=c["claim"])
    assert again == c


def test_release_closes_the_claim_unused(client, data):
    c = take(client)
    r = client.post("/submit/claim", json={"platform": "psc", "version": VERSION, "claim": c["claim"],
                                           "release": True})
    assert r.json() == {"released": True}
    rec = json.load(open(glob.glob(os.path.join(data, "claims", "psc", VERSION, "*.json"))[0]))
    assert rec["closed_by"] == "released"
    # a released section is free to be taken again, and the old claim hands out a fresh one
    assert take(client, claim=c["claim"])["claim"] != c["claim"]
    # releasing twice is harmless
    assert client.post("/submit/claim", json={"platform": "psc", "version": VERSION, "claim": c["claim"],
                                              "release": True}).json() == {"released": True}


def test_release_without_a_claim_is_refused(client):
    r = client.post("/submit/claim", json={"platform": "psc", "version": VERSION, "release": True})
    assert r.status_code == 400


def test_claim_expires_after_claim_hours(client, clock):
    c = take(client)
    clock.advance(hours=47)
    assert take(client, claim=c["claim"])["claim"] == c["claim"]
    clock.advance(hours=2)
    fresh = take(client, claim=c["claim"])
    assert fresh["claim"] != c["claim"]


def test_expired_claims_do_not_count_as_open(client, clock):
    take(client)   # install, claimed
    clock.advance(hours=49)
    assert take(client)["section"]["id"] == "psc-install"   # the old claim is gone: plan order again


def test_settings_json_overrides_the_defaults(client, data):
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "settings.json"), "w") as f:
        json.dump({"target_passes": 5, "claim_hours": 1}, f)
    assert take(client)["expires"] == "2026-10-03T13:00:00Z"
    assert client.get("/submit/coverage").json()["target"] == 5


def test_bad_settings_json_falls_back_to_defaults(client, data):
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "settings.json"), "w") as f:
        f.write("{nope")
    assert client.get("/submit/coverage").json()["target"] == 3


def test_claim_validation(client):
    bad = [{"platform": "amiga", "version": VERSION}, {"platform": "psc", "version": "v9.9.9"},
           {"platform": "psc"}, {"version": VERSION}, {"platform": "psc", "version": "../x"}]
    for body in bad:
        assert client.post("/submit/claim", json=body).status_code == 400, body
    assert client.post("/submit/claim", content=b"not json").status_code == 400
    assert client.post("/submit/claim", json=[1]).status_code == 400


def test_claim_with_a_junk_claim_id_gives_a_new_claim(client):
    c = take(client, claim="../../etc/passwd")
    assert len(c["claim"]) == 16


# ---- results

def test_result_is_stored_and_closes_the_claim(client, data):
    c = take(client)
    r = client.post("/submit/testplan", json=result("psc-install", c["claim"], device="PSC SCPH-1000R",
                                                    contact="me@example.org"))
    assert r.status_code == 200
    rid = r.json()["id"]
    assert len(rid) == 8 and rid.isalnum()
    [path] = glob.glob(os.path.join(data, "testplans", "psc", VERSION, "2026-10-03T120000-%s.json" % rid))
    rec = json.load(open(path))
    assert rec["unassigned"] is False and rec["section"] == "psc-install" and rec["device"] == "PSC SCPH-1000R"
    assert rec["received"] == "2026-10-03T12:00:00Z" and len(rec["steps"]) == 2
    claim = json.load(open(glob.glob(os.path.join(data, "claims", "psc", VERSION, "*.json"))[0]))
    assert claim["closed_by"] == rid
    # a closed claim is not handed out again
    assert take(client, claim=c["claim"])["claim"] != c["claim"]


def test_result_without_a_claim_is_unassigned(client, data):
    rid = client.post("/submit/testplan", json=result()).json()["id"]
    [path] = glob.glob(os.path.join(data, "testplans", "psc", VERSION, "*-%s.json" % rid))
    assert json.load(open(path))["unassigned"] is True


def test_result_with_a_foreign_claim_is_unassigned_and_leaves_the_claim_open(client, data):
    c = take(client)   # a claim on psc-install
    rid = client.post("/submit/testplan", json=result("psc-store", c["claim"])).json()["id"]
    [path] = glob.glob(os.path.join(data, "testplans", "psc", VERSION, "*-%s.json" % rid))
    assert json.load(open(path))["unassigned"] is True
    claim = json.load(open(glob.glob(os.path.join(data, "claims", "psc", VERSION, "*.json"))[0]))
    assert claim["closed_by"] is None
    unknown = client.post("/submit/testplan", json=result("psc-store", "x" * 16)).json()["id"]
    assert len(unknown) == 8


def test_result_with_a_problem_still_counts_as_a_pass(client):
    body = result("psc-install")
    body["steps"][0] = {"id": "psc-install.1", "status": "problem", "comment": "it froze"}
    assert client.post("/submit/testplan", json=body).status_code == 200
    assert client.get("/submit/coverage").json()["platforms"]["psc"]["section"]["id"] == "psc-launcher"


def test_result_validation(client):
    def code(body):
        return client.post("/submit/testplan", json=body).status_code

    assert code(result(platform="amiga")) == 400
    assert code(result(version="v0.0.1")) == 400
    assert code(result(section="psc-nothing")) == 400
    assert code(result(section=None)) == 400
    # an unknown step
    body = result()
    body["steps"][1]["id"] = "psc-install.9"
    assert code(body) == 400
    # a step of another section than the one claimed/submitted
    body = result()
    body["steps"][1]["id"] = "psc-store.1"
    assert code(body) == 400
    # a missing step
    body = result()
    del body["steps"][1]
    assert code(body) == 400
    # a step twice
    body = result()
    body["steps"][1]["id"] = "psc-install.1"
    assert code(body) == 400
    # a bad status
    body = result()
    body["steps"][0]["status"] = "maybe"
    assert code(body) == 400
    # a comment is required on a problem (and a blank one does not do)
    for comment in ("", "   "):
        body = result()
        body["steps"][0] = {"id": "psc-install.1", "status": "problem", "comment": comment}
        assert code(body) == 400
    body = result()
    del body["steps"][0]["status"]
    assert code(body) == 400
    assert code(result(steps="nope")) == 400
    assert code(result(steps=["psc-install.1"])) == 400


def test_result_text_caps(client):
    body = result()
    body["steps"][0]["comment"] = "x" * 2001
    assert client.post("/submit/testplan", json=body).status_code == 400
    body["steps"][0]["comment"] = "x" * 2000
    assert client.post("/submit/testplan", json=body).status_code == 200
    assert client.post("/submit/testplan", json=result(device="d" * 201)).status_code == 400
    assert client.post("/submit/testplan", json=result(contact="c" * 201)).status_code == 400
    assert client.post("/submit/testplan", json=result(device=5)).status_code == 400


def test_a_na_step_needs_no_comment(client):
    body = result()
    body["steps"] = answers(PSC_STEPS["psc-install"], "na")
    assert client.post("/submit/testplan", json=body).status_code == 200


def test_atomic_write_leaves_no_temp_files(client, data):
    take(client)
    client.post("/submit/testplan", json=result())
    post_issue(client, logs=make_zip({"a.log": "x"}))
    names = [os.path.basename(p) for p in files_under(data)]
    assert names and not [n for n in names if n.startswith(".tmp") or n.endswith(".tmp")]


def test_a_failed_write_removes_its_temp_file(tmp_path, monkeypatch):
    from app import store
    target = str(tmp_path / "d" / "x.json")

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store.os, "replace", boom)
    try:
        store.write_atomic(target, b"{}")
    except OSError:
        pass
    assert os.listdir(str(tmp_path / "d")) == []


# ---- the honeypot

def test_honeypot_looks_like_success_and_stores_nothing(client, data):
    r = client.post("/submit/testplan", json=result(website="http://spam.example"))
    assert r.status_code == 200 and len(r.json()["id"]) == 8
    r = post_issue(client, issue_form(website="http://spam.example"))
    assert r.status_code == 200 and len(r.json()["id"]) == 8
    assert files_under(data) == []
    # and it does not use up the sender's quota
    for _ in range(6):
        client.post("/submit/testplan", json=result(website="x"))
    assert client.post("/submit/testplan", json=result()).status_code == 200


# ---- rate limits

def test_rate_limit_five_per_hour_for_results_and_issues_together(client, clock):
    for _ in range(3):
        assert client.post("/submit/testplan", json=result()).status_code == 200
    for _ in range(2):
        assert post_issue(client).status_code == 200
    assert client.post("/submit/testplan", json=result()).status_code == 429
    assert post_issue(client).status_code == 429
    assert "error" in client.post("/submit/testplan", json=result()).json()
    clock.advance(hours=1, minutes=1)
    assert client.post("/submit/testplan", json=result()).status_code == 200


def test_rate_limit_twenty_per_day(client, clock):
    for _ in range(4):
        for _ in range(5):
            assert client.post("/submit/testplan", json=result()).status_code == 200
        clock.advance(minutes=61)
    assert client.post("/submit/testplan", json=result()).status_code == 429
    clock.advance(hours=24)
    assert client.post("/submit/testplan", json=result()).status_code == 200


def test_rate_limit_claims_thirty_per_hour(client, clock):
    for _ in range(30):
        assert client.post("/submit/claim", json={"platform": "psc", "version": VERSION}).status_code == 200
    assert client.post("/submit/claim", json={"platform": "psc", "version": VERSION}).status_code == 429
    # claims and submissions have separate budgets
    assert client.post("/submit/testplan", json=result()).status_code == 200
    clock.advance(hours=1, minutes=1)
    assert client.post("/submit/claim", json={"platform": "psc", "version": VERSION}).status_code == 200


def test_rejected_requests_do_not_use_the_quota(client):
    for _ in range(10):
        assert client.post("/submit/testplan", json=result(section="nope")).status_code == 400
    assert client.post("/submit/testplan", json=result()).status_code == 200


def test_rate_limit_is_per_address_forwarded_by_a_trusted_proxy(make):
    caddy = make()
    for _ in range(5):
        assert caddy.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "203.0.113.5"}
                          ).status_code == 200
    assert caddy.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
                      ).status_code == 429
    assert caddy.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "203.0.113.6"}
                      ).status_code == 200


def test_forwarded_for_is_ignored_from_an_untrusted_peer(make):
    direct = make(peer=("198.51.100.9", 4000))
    for i in range(5):
        assert direct.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "1.1.1.%d" % i}
                           ).status_code == 200
    assert direct.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "9.9.9.9"}
                       ).status_code == 429


def test_a_garbage_forwarded_for_falls_back_to_the_peer(make):
    caddy = make()
    for _ in range(5):
        assert caddy.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "not-an-ip"}
                          ).status_code == 200
    assert caddy.post("/submit/testplan", json=result()).status_code == 429


def test_no_address_is_written_anywhere(client, data):
    client.post("/submit/testplan", json=result(), headers={"X-Forwarded-For": "203.0.113.77"})
    post_issue(client)
    for path in files_under(data):
        content = open(path, "rb").read()
        assert b"203.0.113.77" not in content and b"172.18.0.2" not in content


# ---- coverage

def test_coverage_names_the_most_needed_section_per_platform(client):
    cov = client.get("/submit/coverage").json()
    assert cov["version"] == VERSION and cov["target"] == 3
    assert cov["platforms"] == {
        "psc": {"section": {"id": "psc-install", "title": "Install with the Windows installer and first boot"},
                "passes": 0},
        "rpi": {"section": {"id": "rpi-install", "title": "Write the image and first boot"}, "passes": 0}}
    client.post("/submit/testplan", json=result("psc-install"))
    client.post("/submit/testplan", json=result("psc-launcher"))
    cov = client.get("/submit/coverage").json()
    assert cov["platforms"]["psc"]["section"]["id"] == "psc-store" and cov["platforms"]["psc"]["passes"] == 0


def test_coverage_counts_passes_when_every_section_has_some(client):
    for section in PSC_STEPS:
        client.post("/submit/testplan", json=result(section))
    client.post("/submit/testplan", json=result("psc-install"))
    psc = client.get("/submit/coverage").json()["platforms"]["psc"]
    assert psc["passes"] == 1 and psc["section"]["id"] == "psc-launcher"


def test_coverage_of_an_older_version_and_unknown(client):
    old = client.get("/submit/coverage", params={"version": "v1.9.0"}).json()
    assert old["version"] == "v1.9.0" and list(old["platforms"]) == ["psc"]
    assert client.get("/submit/coverage", params={"version": "v0.0.1"}).status_code == 404


def test_current_version_without_index_json_is_the_highest(tmp_path):
    import shutil
    from conftest import PLANS
    copy = str(tmp_path / "plans")
    shutil.copytree(PLANS, copy)
    os.remove(os.path.join(copy, "index.json"))
    shutil.copytree(os.path.join(copy, "v1.9.0"), os.path.join(copy, "v2.0.0-pre0-abcdef1"))
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    c = TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), plans_dir=copy, salt="s")))
    assert c.get("/submit/coverage").json()["version"] == VERSION   # alpha1 outranks a pre0 build


# ---- issues

def test_issue_without_logs(client, data):
    r = post_issue(client, issue_form(contact="me@example.org"))
    assert r.status_code == 200
    rid = r.json()["id"]
    [path] = glob.glob(os.path.join(data, "issues", "2026-10-03", rid, "report.json"))
    rec = json.load(open(path))
    assert rec["has_logs"] is False and rec["actual"] == "it crashes" and rec["contact"] == "me@example.org"
    assert not os.path.exists(os.path.join(os.path.dirname(path), "logs.zip"))


def test_issue_with_logs_and_consent(client, data):
    zipped = make_zip({"launcher.log": "hello", "sub/dir/other.log": "x"})
    r = post_issue(client, issue_form(consent_logs="on"), logs=zipped)
    assert r.status_code == 200
    rid = r.json()["id"]
    folder = os.path.join(data, "issues", "2026-10-03", rid)
    assert open(os.path.join(folder, "logs.zip"), "rb").read() == zipped
    assert json.load(open(os.path.join(folder, "report.json")))["has_logs"] is True
    assert sorted(os.listdir(folder)) == ["logs.zip", "report.json"]


def test_issue_logs_need_consent(client, data):
    r = post_issue(client, logs=make_zip({"a": "b"}))
    assert r.status_code == 400
    assert files_under(data) == []


def test_issue_validation(client):
    for missing in ("steps", "expected", "actual", "platform", "version"):
        form = issue_form()
        del form[missing]
        assert post_issue(client, form).status_code == 400, missing
    assert post_issue(client, issue_form(platform="amiga")).status_code == 400
    assert post_issue(client, issue_form(version="v0.0.1")).status_code == 400


def test_issue_text_caps(client):
    for key in ("steps", "expected", "actual"):
        assert post_issue(client, issue_form(**{key: "x" * 5001})).status_code == 400
        assert post_issue(client, issue_form(**{key: "x" * 5000})).status_code == 200
    assert post_issue(client, issue_form(contact="c" * 201)).status_code == 400


def test_issue_refuses_a_non_zip(client, data):
    assert post_issue(client, issue_form(consent_logs="on"), logs=b"just text").status_code == 400
    assert post_issue(client, issue_form(consent_logs="on"), logs=make_zip({"a": "b"}), name="logs.tar"
                      ).status_code == 400
    assert files_under(data) == []


def test_issue_refuses_path_traversal(client, data):
    for name in ("../evil.sh", "a/../../evil", "/etc/passwd", "\\windows\\x", "C:\\x"):
        r = post_issue(client, issue_form(consent_logs="on"), logs=make_zip({name: "x"}))
        assert r.status_code == 400, name
    assert files_under(data) == []


def test_issue_refuses_a_zip_bomb_by_total_size(make, data):
    small = make(max_zip_total=1000)
    bomb = make_zip({"a.log": "0" * 5000})
    assert len(bomb) < 1000   # small on the wire, big unpacked
    assert post_issue(small, issue_form(consent_logs="on"), logs=bomb).status_code == 400
    ok = make_zip({"a.log": "0" * 500})
    assert post_issue(small, issue_form(consent_logs="on"), logs=ok).status_code == 200


def test_issue_refuses_too_many_entries(make):
    c = make(max_zip_entries=3)
    many = make_zip({"f%d" % i: "x" for i in range(4)})
    assert post_issue(c, issue_form(consent_logs="on"), logs=many).status_code == 400


def test_the_zip_is_never_extracted(client, data):
    post_issue(client, issue_form(consent_logs="on"), logs=make_zip({"launcher.log": "hello"}))
    assert "launcher.log" not in [os.path.basename(p) for p in files_under(data)]


# ---- size limits

def test_result_body_over_256_kb_is_refused(client):
    r = client.post("/submit/testplan", json=result(device="x" * (256 * 1024)))
    assert r.status_code == 413 and "error" in r.json()


def test_result_body_limit_holds_without_a_content_length(client):
    def chunks():
        for _ in range(300):
            yield b" " * 1024
    r = client.post("/submit/testplan", content=chunks())
    assert r.status_code == 413


def test_issue_body_over_25_mb_is_refused(make, data):
    c = make()
    big = make_zip({"a.log": os.urandom(1024)})
    r = c.post("/submit/issue", data=issue_form(consent_logs="on"),
               files={"logs": ("logs.zip", big + b"\0" * (25 * 1024 * 1024), "application/zip")})
    assert r.status_code == 413
    assert files_under(data) == []


def test_claim_body_is_small(client):
    r = client.post("/submit/claim", json={"platform": "psc", "version": VERSION, "pad": "x" * 20000})
    assert r.status_code == 413


# ---- status

def test_status_of_a_result_and_an_issue(client):
    rid = client.post("/submit/testplan", json=result()).json()["id"]
    got = client.get("/submit/status/" + rid).json()
    assert got == {"id": rid, "kind": "testplan", "received": "2026-10-03T12:00:00Z", "state": "received"}
    iid = post_issue(client).json()["id"]
    got = client.get("/submit/status/" + iid).json()
    assert got["kind"] == "issue" and got["state"] == "received" and set(got) == {"id", "kind", "received", "state"}


def test_status_follows_the_panels_decision(client, data):
    iid = post_issue(client).json()["id"]
    os.makedirs(os.path.join(data, "decisions"), exist_ok=True)
    for state in ("needs-info", "to-reproduce", "bug BUG-12", "not-a-bug", "idea"):
        with open(os.path.join(data, "decisions", iid + ".json"), "w") as f:
            json.dump({"state": state, "reason": "private note", "by": "someone", "at": "2026-10-03"}, f)
        got = client.get("/submit/status/" + iid).json()
        assert got["state"] == state and "reason" not in got and "by" not in got


def test_status_with_a_broken_decision_file_is_received(client, data):
    iid = post_issue(client).json()["id"]
    os.makedirs(os.path.join(data, "decisions"), exist_ok=True)
    with open(os.path.join(data, "decisions", iid + ".json"), "w") as f:
        f.write("{broken")
    assert client.get("/submit/status/" + iid).json()["state"] == "received"


def test_status_unknown_and_malformed_ids(client):
    assert client.get("/submit/status/abcd1234").status_code == 404
    assert client.get("/submit/status/..%2F..%2Fsettings").status_code == 404
    assert client.get("/submit/status/ABCDEFGH").status_code == 404
    assert client.get("/submit/status/*").status_code == 404
    assert client.get("/submit/status/abcd1234").json() == {"error": "unknown id"}


# ---- the shared group (the admin panel reads this volume and writes decisions/)

def test_modes_are_group_shared_whatever_the_umask(client, data):
    old = os.umask(0o077)
    try:
        take(client)
        client.post("/submit/testplan", json=result())
        post_issue(client, issue_form(consent_logs="on"), logs=make_zip({"a": "b"}))
    finally:
        os.umask(old)
    for path in files_under(data):
        assert os.stat(path).st_mode & 0o777 == 0o640, path
    for folder in [d for d, _, _ in os.walk(data)]:
        assert os.stat(folder).st_mode & 0o7777 == 0o2770, folder
    assert os.path.isdir(os.path.join(data, "decisions"))   # made at start, for the panel to write into


def test_version_order_puts_a_point_release_between_its_number_and_the_next():
    from app.store import version_key
    tags = ["v2.0.0-alpha2", "v2.0.0-alpha1.10", "v2.0.0-alpha1.2", "v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-beta1"]
    assert sorted(tags, key=version_key) == ["v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-alpha1.2",
                                              "v2.0.0-alpha1.10", "v2.0.0-alpha2", "v2.0.0-beta1"]
