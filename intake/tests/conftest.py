import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["AB_INTAKE_NO_APP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

PLANS = os.path.join(os.path.dirname(__file__), "fixtures", "testplans")
VERSION = "v2.0.0-alpha1"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def data(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def make(data, clock):
    """make(**settings) -> a TestClient on a fresh app over the same data dir; the peer defaults to a Caddy-like one."""
    def build(peer=("172.18.0.2", 5000), **kw):
        s = Settings(data_dir=data, plans_dir=PLANS, salt="test-salt", **kw)
        return TestClient(create_app(s, clock), client=peer)
    return build


@pytest.fixture
def client(make):
    return make()


def answers(section_steps, status="ok", comment=""):
    return [{"id": i, "status": status, "comment": comment} for i in section_steps]


PSC_STEPS = {"psc-install": ["psc-install.1", "psc-install.2"],
             "psc-launcher": ["psc-launcher.1", "psc-launcher.2"],
             "psc-store": ["psc-store.1"]}


def result(section="psc-install", claim=None, **extra):
    steps = answers(PSC_STEPS.get(section, ["x.1"]))
    body = {"platform": "psc", "version": VERSION, "section": section, "steps": steps}
    if claim:
        body["claim"] = claim
    body.update(extra)
    return body


def take(client, platform="psc", **extra):
    r = client.post("/submit/claim", json={"platform": platform, "version": VERSION, **extra})
    assert r.status_code == 200, r.text
    return r.json()
