"""A local preview of the admin panel: the same app, over a fake GitHub and a fake site tree with
realistic data (an in-progress run with steps, a queued run, two runners, finished runs, a store
catalog), no auth (every request is answered as if "alice", a release-manager, were logged in) - so
the page can be looked at in a browser without a GitHub App or oauth2-proxy.

    cd admin && python tools/dev_server.py

Then open http://127.0.0.1:8765/admin/ . Ctrl-C to stop; nothing here is written outside a temp dir
that is thrown away on exit.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # admin/, for `app` and `tests`

from tests.intake_data import write_intake, write_plans  # noqa: E402  (the tester tabs' sample data)
from tests.test_admin import FakeGitHub, run  # noqa: E402  (the same fake the test suite uses)

from app import main  # noqa: E402
from app.config import Settings  # noqa: E402

HOST, PORT = "127.0.0.1", 8765


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_github():
    now = datetime.now(timezone.utc)
    gh = FakeGitHub()
    gh.runs["autobleem"] = [
        run(201, "in_progress", None, start=iso(now - timedelta(minutes=6)), end=None),
        run(202, "queued", None, start=None, end=None, created=iso(now - timedelta(minutes=2))),
        run(150, "completed", "success", start=iso(now - timedelta(hours=2)),
            end=iso(now - timedelta(hours=2) + timedelta(minutes=18))),
        run(149, "completed", "failure", start=iso(now - timedelta(hours=5)),
            end=iso(now - timedelta(hours=5) + timedelta(minutes=7))),
    ]
    gh.jobs[201] = [
        {"name": "build (psc)", "status": "in_progress", "html_url": "https://github.com/x/201",
         "runner_name": "psc-build-1", "labels": ["self-hosted", "psc"],
         "steps": [
             {"number": 1, "name": "Checkout", "status": "completed", "conclusion": "success",
              "started_at": iso(now - timedelta(minutes=6)), "completed_at": iso(now - timedelta(minutes=5, seconds=50))},
             {"number": 2, "name": "Configure", "status": "completed", "conclusion": "success",
              "started_at": iso(now - timedelta(minutes=5, seconds=50)), "completed_at": iso(now - timedelta(minutes=4))},
             {"number": 3, "name": "Build", "status": "in_progress", "conclusion": None,
              "started_at": iso(now - timedelta(minutes=4)), "completed_at": None},
             {"number": 4, "name": "Package", "status": "queued", "conclusion": None,
              "started_at": None, "completed_at": None},
         ]},
        {"name": "build (win)", "status": "queued", "html_url": "https://github.com/x/201-win",
         "runner_name": None, "labels": ["self-hosted", "windows"], "started_at": None, "steps": []},
    ]
    gh.runners = [
        {"id": 1, "name": "psc-build-1", "status": "online", "busy": True,
         "labels": [{"name": "self-hosted"}, {"name": "psc"}]},
        {"id": 2, "name": "pc-build-1", "status": "online", "busy": False,
         "labels": [{"name": "self-hosted"}, {"name": "windows"}, {"name": "pcusb"}]},
    ]
    gh.contents["docs/bugs.md"] = BUGS_MD
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "todo_state.md"), encoding="utf-8") as f:
        gh.contents["docs/todo.md"] = f.read()  # the Tasks tab preview
    return gh


# A trimmed, realistic docs/bugs.md (PLATFORM-9) for the Bugs tab preview - open bugs of every severity and
# a mix of platforms, plus a closed/wontfix/duplicate one for the folded section.
BUGS_MD = """# Known bugs

| BUG | Title | Platform | Severity | State | Found | Fix |
|---|---|---|---|---|---|---|
| BUG-1 | A game starts by itself after leaving Options | psc | major | fixed-untested | console session, 2026-09-27 | [CONSOLE-11](todo.md) |
| BUG-2 | Pad-mapping wizard: analog mapping does not work | psc | major | confirmed | console session, 2026-09-27 | [TOOLS-9](todo.md) |
| BUG-6 | The mouse pointer shows after a Bluetooth pad reconnects | psc | major | confirmed | console, 2026-09-26 | [KERNEL-6](todo.md) |
| BUG-9 | In-game notices are drawn under the scanlines | psc, rpi, pcusb, win | minor | fixing | console session, 2026-09-27 | [EMU-15](todo.md) |
| BUG-10 | Bluetooth cannot pair on a Pi when rfkill soft-blocks it | rpi | major | confirmed | Pi 400 test, 2026-09-27 | [TOOLS-10](todo.md) |
| BUG-13 | The pad is dead for 1-3 s after every game on a Pi 400 | rpi | minor | open | Pi 400 test | - |
| BUG-14 | The homebrew RSP tests crash a core; never tried with a real game | rpi, pcusb, win | minor | open | RetroArch core tests | [EMU-12](todo.md) |
| BUG-18 | A `dpkg -S` pipe could hit the same SIGPIPE race as BUG-16 | all | minor | open | code review | - |
| BUG-97 | Blocker used only to show the sort order in this preview | psc | blocker | open | preview data | - |
| BUG-11 | No notice when pad swap is on but the emulator lacks support | psc | minor | wontfix | console session, 2026-09-27 (no longer developed) | - |
| BUG-99 | Reported twice by two testers on the same day | rpi | major | duplicate of BUG-10 | Pi 400 test, 2026-09-27 | - |
| BUG-16 | A version print piped into `head` under `pipefail` exits 141 at random | all | minor | closed | CI run, 2026-09-27; fixed and verified on a green run | - |
"""


def build_site_tree(root):
    (root / "releases").mkdir(parents=True)
    (root / "nightly").mkdir()
    (root / "releases" / "latest.json").write_text(json.dumps(
        {"version": "v2.0.0", "prerelease": False, "files": {"psc-fs": {}, "rpi": {}, "win": {}}, "date": "2026-09-01"}))
    (root / "releases" / "unstable.json").write_text(json.dumps(
        {"version": "v2.1.0-beta2", "prerelease": True, "files": {"psc-fs": {}, "rpi": {}}, "date": "2026-09-20"}))
    (root / "nightly" / "latest.json").write_text(json.dumps(
        {"version": "v2.1.0-beta2-14-gabc1234", "files": {"psc-fs": {}, "rpi": {}, "pcusb": {}},
         "images": {"armhf": {}, "arm64": {}}, "date": "2026-09-26"}))
    (root / "pc" / "images").mkdir(parents=True)
    (root / "pc" / "images" / "release.json").write_text(json.dumps({"version": "v2.0.0"}))
    for platform, items in (
        ("psc", [{"id": "app/opentyrian", "kind": "app", "title": "OpenTyrian", "version": "2.1",
                  "files": [{"name": "opentyrian-psc-2.1.zip", "size": 4_200_000}]},
                 {"id": "ps1/example", "kind": "ps1", "title": "Example Game", "version": "1.0",
                  "files": [{"name": "example.zip", "size": 512_000_000}, {"name": "example.png", "size": 45_000}]}]),
        ("win", [{"id": "app/terminal", "kind": "app", "title": "Terminal", "version": "1.3",
                  "files": [{"name": "terminal-win-1.3.zip", "size": 900_000}]}]),
    ):
        d = root / "store" / platform
        d.mkdir(parents=True)
        (d / "catalog.json").write_text(json.dumps(
            {"schema": 1, "platform": platform, "date": "2026-09-25", "items": items}))


def main_():
    import uvicorn
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="ab-admin-dev-") as tmp:
        tmp = Path(tmp)
        site = tmp / "site"
        build_site_tree(site)
        write_plans(str(site))
        write_intake(str(tmp / "intake"))  # the tester tabs' sample data
        settings = Settings(repo_dir=str(site), data_dir=str(tmp / "data"), repos=["autobleem"],
                            org="autobleem2", release_team="release-managers", intake_dir=str(tmp / "intake"))
        gh = build_github()
        gh.members.add("alice")
        gh.managers.add("alice")
        app = main.create_app(settings, gh=gh, start_notifier=False)
        asgi = InjectUser(app, "alice")
        print("AutoBleem admin dev preview: http://%s:%d/admin/ (logged in as 'alice', a release manager)"
             % (HOST, PORT))
        uvicorn.run(asgi, host=HOST, port=PORT, log_level="warning")


class InjectUser:
    """wraps the ASGI app so every request looks like it already went through oauth2-proxy as `login` -
    no GitHub App, no browser login needed for a local look at the page"""

    def __init__(self, app, login):
        self.app = app
        self.header = (b"x-forwarded-user", login.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, headers=[*scope.get("headers", []), self.header])
        await self.app(scope, receive, send)


if __name__ == "__main__":
    main_()
