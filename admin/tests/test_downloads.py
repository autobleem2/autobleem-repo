"""The download counter: the log parser, the incremental read (rotation, partial lines, no double count), the
classification of a path, and the admin endpoint (release team only).

    cd admin && python -m pytest -q
"""
import json
import os
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["AB_ADMIN_NO_APP"] = "1"
from app import main  # noqa: E402
from app.config import Settings  # noqa: E402
from app.downloads import Downloads, classify, parse_line  # noqa: E402
from tests.test_admin import FakeGitHub, browser  # noqa: E402

TS = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc).timestamp()


def line(uri, status=200, method="GET", ts=TS):
    return json.dumps({"level": "info", "ts": ts, "msg": "handled request", "status": status, "size": 10,
                       "request": {"method": method, "host": "x", "uri": uri}}) + "\n"


def test_parse_counts_a_full_download_only():
    assert parse_line(line("/releases/v2.0.0/ab-psc.zip")) == ("2026-10-03", "releases/v2.0.0/ab-psc.zip")
    assert parse_line(line("/manuals/Guide%20EN.pdf?x=1")) == ("2026-10-03", "manuals/Guide EN.pdf")
    assert parse_line(line("/a.zip", status=404)) is None
    assert parse_line(line("/a.zip", status=206)) is None
    assert parse_line(line("/a.zip", status=304)) is None
    assert parse_line(line("/a.zip", method="HEAD")) is None
    assert parse_line(line("/releases/latest.json")) is None       # a catalog check is not a download
    assert parse_line(line("/index.html")) is None
    assert parse_line(line("/admin/api/x.zip")) is None
    assert parse_line(line("/a/../b.zip")) is None
    assert parse_line("not json\n") is None
    assert parse_line('{"status": 200}\n') is None


def test_classify_reads_what_the_path_says():
    assert classify("releases/v2.0.0-alpha2/ab-psc-v2.0.0-alpha2.zip") == {
        "group": "releases", "platform": "psc", "version": "v2.0.0-alpha2", "channel": "testing"}
    assert classify("releases/v2.1.0/ab-rpi64.img.xz")["channel"] == "release"
    assert classify("releases/v2.1.0/ab-rpi64.img.xz")["platform"] == "rpi64"
    assert classify("nightly/ab-pcusb-2.0.0-20261003-abc1234.zip")["channel"] == "nightly"
    assert classify("preview/feature-x/ab-psc.zip")["channel"] == "preview"
    s = classify("store/win/app-1.2.3.zip")
    assert (s["group"], s["platform"], s["version"]) == ("store", "windows", "1.2.3")
    assert classify("manuals/guide.pdf") == {"group": "manuals", "platform": "", "version": "", "channel": ""}


@pytest.fixture
def dl(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    return Downloads(Settings(data_dir=str(tmp_path / "data"), log_dir=str(logs))), logs / "access.log"


def test_incremental_read_never_counts_twice(dl):
    d, log = dl
    log.write_text(line("/a/x.zip") + line("/a/x.zip") + line("/a/y.zip", 404))
    assert d.ingest() == 2
    assert d.ingest() == 0
    with open(log, "a") as f:
        f.write(line("/a/x.zip"))
        f.write(line("/a/x.zip")[:20])          # a half-written line waits for its end
    assert d.ingest() == 1
    with open(log, "a") as f:
        f.write(line("/a/x.zip")[20:])
    assert d.ingest() == 1
    rep = d.report(today=date(2026, 10, 3))
    assert [(f["path"], f["total"]) for f in rep["files"]] == [("a/x.zip", 4)]


def test_rotation_is_followed(dl):
    d, log = dl
    log.write_text(line("/a/x.zip") + line("/a/x.zip"))
    d.ingest()
    with open(log, "a") as f:
        f.write(line("/a/x.zip"))               # written, not yet read, then Caddy rotates
    os.rename(log, log.with_name("access-2026-10-03T12-00-00.000.log"))
    log.write_text(line("/a/y.zip"))
    assert d.ingest() == 2                       # the rotated file's tail and the new file
    assert d.ingest() == 0
    rep = d.report(today=date(2026, 10, 3))
    assert {f["path"]: f["total"] for f in rep["files"]} == {"a/x.zip": 3, "a/y.zip": 1}
    os.remove(log.with_name("access-2026-10-03T12-00-00.000.log"))   # Caddy's keep limit deletes it
    assert d.ingest() == 0


def test_a_truncated_or_replaced_log_starts_again(dl):
    d, log = dl
    log.write_text(line("/a/x.zip") * 3)
    d.ingest()
    log.write_text(line("/a/z.zip"))             # same name (and maybe inode), shorter: a new file
    assert d.ingest() == 1


def test_report_windows_and_splits(dl):
    d, log = dl
    day = lambda y, m, dd: datetime(y, m, dd, 9, tzinfo=timezone.utc).timestamp()
    log.write_text(line("/releases/v1.0.0/a-psc.zip", ts=day(2026, 10, 3))
                   + line("/releases/v1.0.0/a-psc.zip", ts=day(2026, 10, 1))
                   + line("/releases/v1.0.0/a-psc.zip", ts=day(2026, 9, 20))
                   + line("/nightly/b-rpi.zip", ts=day(2026, 7, 1)))
    d.ingest()
    r = d.report(today=date(2026, 10, 3))
    assert (r["today"], r["last7"], r["last30"], r["total"], r["since"]) == (1, 2, 3, 4, "2026-07-01")
    assert [f["path"] for f in r["top"]] == ["releases/v1.0.0/a-psc.zip"]
    plat = {p["name"]: p["last30"] for p in r["platforms"]}
    assert plat == {"psc": 3, "rpi": 0}
    assert {c["name"]: c["total"] for c in r["channels"]} == {"release": 3, "nightly": 1}
    assert len(r["days"]) == 30 and r["days"][-1] == {"day": "2026-10-03", "n": 1}


def test_no_log_yet_is_an_empty_report(dl):
    d, _ = dl
    assert d.ingest() == 0
    r = d.report()
    assert r["total"] == 0 and r["top"] == [] and r["since"] is None


def test_endpoint_is_the_release_teams(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "access.log").write_text(line("/releases/v1.0.0/a-psc.zip", ts=datetime.now(timezone.utc).timestamp()))
    settings = Settings(repo_dir=str(tmp_path), data_dir=str(tmp_path / "data"), log_dir=str(logs), repos=[])
    client = TestClient(main.create_app(settings, gh=FakeGitHub(), start_notifier=False))
    assert client.get("/admin/api/downloads").status_code == 401
    assert client.get("/admin/api/downloads", headers=browser("eve")).status_code == 403
    assert client.get("/admin/api/downloads", headers=browser("bob")).status_code == 403   # a member, not release team
    r = client.get("/admin/api/downloads", headers=browser("alice"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["today"] == 1 and body["files"][0]["platform"] == "psc"
    assert r.headers["cache-control"] == "no-store"
