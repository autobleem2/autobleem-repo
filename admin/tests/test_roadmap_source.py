"""R27: the files the roadmap tab reads (todo.md, roadmap.md, the how-to pages), over a fake contents API.

    cd admin && python -m pytest -q
"""
import base64

from app.config import Settings
from app.github import GitHubError
from app.roadmap_source import RoadmapSource


class FakeContents:
    def __init__(self, files):
        self.files, self.paths = files, []

    def cached(self, key, ttl, fn):
        return fn()

    def call(self, method, path, body=None):
        self.paths.append(path)
        name = path.split("/contents/", 1)[1].split("?", 1)[0]
        if name not in self.files:
            raise GitHubError(404, "Not Found")
        return {"content": base64.b64encode(self.files[name].encode("utf-8")).decode("ascii")}


def source(files):
    return RoadmapSource(FakeContents(files), Settings())


def test_roadmap_reads_todo_with_the_state_column():
    todo = "## UIREV - x\n\n| ID | What | Where | Size | Who | Ms | State |\n|---|---|---|---|---|---|---|\n" \
           "| UIREV-1 | x | y | S | dev | alpha1 | done |\n| UIREV-2 | z | y | S | dev | alpha1 | new |\n"
    s = source({"docs/todo.md": todo})
    got = s.roadmap()
    assert [(r["id"], r["state"], r["done"]) for r in got["rows"]] == [("UIREV-1", "done", True),
                                                                       ("UIREV-2", "new", False)]
    assert got["milestones"] == []
    assert s.gh.paths[0] == "/repos/autobleem2/autobleem-main/contents/docs/todo.md?ref=develop"


def test_a_howto_page_is_served():
    s = source({"howto/claude-login.html": "<h1>Logowanie</h1>"})
    assert s.howto("claude-login") == "<h1>Logowanie</h1>"
    assert s.gh.paths[-1] == "/repos/autobleem2/autobleem-main/contents/howto/claude-login.html?ref=develop"


def test_a_howto_name_never_leaves_the_folder():
    s = source({"howto/x.html": "x"})
    assert s.howto("missing") is None
    for bad in ("../status", "a/b", "X", "", "a.html"):
        assert s.howto(bad) is None
    assert all("/contents/howto/" in p for p in s.gh.paths)
