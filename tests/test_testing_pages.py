"""The volunteer tester pages (PLATFORM: tester portal): testplans/<version>/<platform>.yaml -> testplans/index.json
and the pages under testing/. The contract with the intake service is intake/README.md."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
BASE_URL = "https://example.test"

PLAN = '''# a comment line
id: psc
title: "PlayStation Classic"
version: %(version)s
before_you_start:
  - "Get: the installer from the <b>download</b> page."
  - "A path like C:\\\\Games and a 'quote'."
sections:
  - id: psc-install
    title: "Install </script><script>alert(1)</script>"
    minutes: 10
    needs: "A Windows PC & a stick."
    steps:
      - id: psc-install.1
        do: "Unzip it and run <i>the installer</i>."
        expect: "A window with the Channel box."
        status: ""
        comment: ""
      - id: psc-install.2
        do: 'Press Install - it''s quick.'
        expect: "It ends with the stick named SONY."
        status: ""
        comment: ""
  - id: psc-store
    title: "Store"
    minutes: 8
    needs: ""
    steps:
      - id: psc-store.1
        do: "Open the Store."
        expect: "A list."
'''


def make_repo(tmp_path, versions=("v2.0.0-alpha1",), platforms=("psc",)):
    for v in versions:
        folder = tmp_path / "testplans" / v
        folder.mkdir(parents=True)
        for p in platforms:
            text = (PLAN % {"version": v}).replace("id: psc\n", "id: %s\n" % p, 1)
            (folder / (p + ".yaml")).write_text(text, encoding="utf-8")
    return str(tmp_path)


def generate(tmp_path, **kw):
    repo = make_repo(tmp_path, **kw)
    info = repo_index.index_testplans(repo)
    if info:
        os.makedirs(os.path.join(repo, "testing"), exist_ok=True)
        for name, page in repo_index.testing_pages(info):
            with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
                f.write(page)
    return repo, info


def read(repo, *parts):
    with open(os.path.join(repo, *parts), encoding="utf-8") as f:
        return f.read()


def test_yaml_subset_parses_the_plan_files():
    plan = repo_index.parse_plan_yaml(PLAN % {"version": "v2.0.0-alpha1"})
    assert plan["id"] == "psc" and plan["version"] == "v2.0.0-alpha1"
    assert plan["before_you_start"][1] == "A path like C:\\Games and a 'quote'."
    s = plan["sections"][0]
    assert s["minutes"] == 10 and len(s["steps"]) == 2
    assert s["steps"][1]["do"] == "Press Install - it's quick."
    assert s["steps"][0]["status"] == "" and plan["sections"][1]["needs"] == ""


def test_index_json_current_version_and_platforms(tmp_path):
    repo, info = generate(tmp_path, versions=("v2.0.0-alpha1", "v2.0.0-pre0", "v2.0.0-alpha2"),
                          platforms=("psc", "win", "rpi"))
    index = json.loads(read(repo, "testplans", "index.json"))
    assert index["current"] == "v2.0.0-alpha2"
    assert index["versions"] == ["v2.0.0-alpha2", "v2.0.0-alpha1", "v2.0.0-pre0"]
    assert list(index["platforms"]) == ["psc", "rpi", "win"]
    assert index["platforms"]["psc"] == {"title": "PlayStation Classic", "sections": 2, "minutes": 18}
    assert info["current"] == "v2.0.0-alpha2"


def test_pages_for_each_platform_and_the_fixed_pages(tmp_path):
    repo, _ = generate(tmp_path, platforms=("psc", "rpi", "pcusb", "win"))
    for name in ("index", "report", "thanks", "status", "psc", "rpi", "pcusb", "win"):
        page = read(repo, "testing", name + ".html")
        assert page.startswith("<!DOCTYPE html>") and "Red Hat Text" in page
        assert "/assets/emblem.png" in page
    landing = read(repo, "testing", "index.html")
    for p in ("psc", "rpi", "pcusb", "win"):
        assert 'href="/testing/%s.html"' % p in landing and 'data-p="%s"' % p in landing
    assert "Give me a task (~10 min)" in landing and "/submit/coverage" in landing
    assert 'href="/testing/report.html"' in landing
    assert "Printable version" not in landing


def test_printable_plan_is_linked_only_when_it_is_there(tmp_path):
    repo, _ = generate(tmp_path)
    (tmp_path / "testplans" / "v2.0.0-alpha1" / "psc.pdf").write_bytes(b"%PDF")
    info = repo_index.index_testplans(repo)
    landing = repo_index.render_testing_index(info)
    assert "/testplans/v2.0.0-alpha1/psc.pdf" in landing and "Printable version" in landing


def test_the_bar_links_testing_only_when_the_site_has_plans(tmp_path):
    bar = lambda: repo_index.page_head("t", "x").split("</header>")[0]  # noqa: E731
    assert repo_index.index_testplans(str(tmp_path)) is None
    assert "Testing" not in bar()
    repo, _ = generate(tmp_path)
    assert '<a href="/testing/">Testing</a><a href="https://github.com/autobleem2">GitHub</a>' in bar()
    assert '<a href="/testing/">Testing</a>' in read(repo, "testing", "psc.html")
    # a tree without plans after one with them: the link is gone again
    assert repo_index.index_testplans(str(tmp_path / "empty")) is None
    assert "Testing" not in bar()


def test_main_puts_the_testing_link_on_every_page_of_a_site_with_plans(tmp_path):
    make_repo(tmp_path)
    out = subprocess.run([sys.executable, os.path.join(TOOLS, "repo_index.py"), str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    for name in (("repository", "index.html"), ("repository", "rpi-install.html")):
        assert '<a href="/testing/">Testing</a>' in read(str(tmp_path), *name)


def test_task_page_embeds_every_section_escaped(tmp_path):
    repo, _ = generate(tmp_path)
    page = read(repo, "testing", "psc.html")
    start = page.index('id="plan-data">') + len('id="plan-data">')
    data = json.loads(page[start:page.index("</script>", start)])
    assert data["platform"] == "psc" and data["version"] == "v2.0.0-alpha1"
    assert [s["id"] for s in data["sections"]] == ["psc-install", "psc-store"]
    assert [st["id"] for st in data["sections"][0]["steps"]] == ["psc-install.1", "psc-install.2"]
    assert data["sections"][0]["steps"][0]["do"] == "Unzip it and run <i>the installer</i>."
    assert "status" not in data["sections"][0]["steps"][0]
    # plan text never reaches the page as markup: no raw tag, the data block cannot close itself
    assert "<script>alert(1)" not in page and "</script><script>" not in page
    assert "<i>the installer</i>" not in page and "\\u003ci\\u003e" in page
    assert "<b>download</b>" not in page and "&lt;b&gt;download&lt;/b&gt;" in page
    # the script only builds nodes from text and talks to the endpoints of the contract
    assert "innerHTML" not in page and "/submit/claim" in page and "/submit/testplan" in page
    assert "localStorage" in page and "release:true" in page


def test_report_page_has_the_honeypot_the_consent_tick_and_the_versions(tmp_path):
    repo, _ = generate(tmp_path, versions=("v2.0.0-alpha1", "v2.0.0-alpha2"))
    page = read(repo, "testing", "report.html")
    assert 'name="website"' in page and 'class="hp"' in page and 'tabindex="-1"' in page
    assert 'type="checkbox"' in page and 'name="consent_logs"' in page
    assert 'name="logs"' in page and 'accept=".zip"' in page
    assert '<option value="v2.0.0-alpha2">' in page and '<option value="v2.0.0-alpha1">' in page
    assert "Other / not sure" in page and 'multipart/form-data' in page and "/submit/issue" in page
    assert "read only by the project" in page and 'type="email"' in page


def test_thanks_and_status_pages(tmp_path):
    repo, _ = generate(tmp_path)
    thanks = read(repo, "testing", "thanks.html")
    assert "Take another task" in thanks and 'id="again"' in thanks
    status = read(repo, "testing", "status.html")
    assert "/submit/status/" in status and "not-a-bug" in status


def test_no_testplans_folder_means_no_pages_and_no_error(tmp_path):
    (tmp_path / "releases").mkdir()
    assert repo_index.index_testplans(str(tmp_path)) is None
    # a folder with no usable plan is the same
    (tmp_path / "testplans" / "v1").mkdir(parents=True)
    (tmp_path / "testplans" / "v1" / "psc.yaml").write_text("id: psc\n", encoding="utf-8")
    assert repo_index.index_testplans(str(tmp_path)) is None
    assert not (tmp_path / "testplans" / "index.json").exists()
    assert not (tmp_path / "testing").exists()


def test_main_writes_the_testing_pages_and_still_runs_without_plans(tmp_path):
    out = subprocess.run([sys.executable, os.path.join(TOOLS, "repo_index.py"), str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert not (tmp_path / "testing").exists() and (tmp_path / "index.html").exists()
    make_repo(tmp_path)
    out = subprocess.run([sys.executable, os.path.join(TOOLS, "repo_index.py"), str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "testing" / "psc.html").exists() and (tmp_path / "testplans" / "index.json").exists()


def run_publish(tmp_path, *args):
    env = dict(os.environ, REPO_DIR=str(tmp_path / "site"), AB_REPO_URL=BASE_URL)
    return subprocess.run(["bash", os.path.join(TOOLS, "repo_publish.sh"), "--local", *args],
                          capture_output=True, text=True, env=env)


def test_publish_kind_testplans_files_each_plan_under_its_own_version_and_indexes(tmp_path):
    import shutil
    if not (shutil.which("bash") and shutil.which("git") and shutil.which("python3")):
        import pytest
        pytest.skip("needs bash, git and python3 (a CI/Linux job)")
    hub = tmp_path / "hub" / "testing" / "alpha1"   # the hub's folder name is not the version
    hub.mkdir(parents=True)
    plan = hub / "psc.yaml"
    plan.write_text(PLAN % {"version": "v2.0.0-alpha1"}, encoding="utf-8")
    out = run_publish(tmp_path, "testplans", str(plan))
    assert out.returncode == 0, out.stderr + out.stdout
    site = tmp_path / "site"
    assert (site / "testplans" / "v2.0.0-alpha1" / "psc.yaml").is_file()
    assert not (site / "testplans" / "alpha1").exists()
    assert not list((site / "testplans").rglob("*.yaml.sha256"))
    assert json.loads((site / "testplans" / "index.json").read_text())["current"] == "v2.0.0-alpha1"
    assert (site / "testing" / "psc.html").is_file()
    # only <platform>.yaml files with a usable version: line are accepted
    bad = hub / "notes.txt"
    bad.write_text("version: v1\n", encoding="utf-8")
    assert run_publish(tmp_path, "testplans", str(bad)).returncode != 0
    noversion = hub / "win.yaml"
    noversion.write_text("id: win\n", encoding="utf-8")
    assert run_publish(tmp_path, "testplans", str(noversion)).returncode != 0


def test_publish_kind_testplans_files_a_pdf_beside_its_yaml_and_refuses_a_lone_pdf(tmp_path):
    import shutil
    if not (shutil.which("bash") and shutil.which("git") and shutil.which("python3")):
        import pytest
        pytest.skip("needs bash, git and python3 (a CI/Linux job)")
    hub = tmp_path / "hub" / "testing" / "alpha1"
    hub.mkdir(parents=True)
    plan, pdf, lone = hub / "psc.yaml", hub / "psc.pdf", hub / "rpi.pdf"
    plan.write_text(PLAN % {"version": "v2.0.0-alpha1"}, encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4")
    lone.write_bytes(b"%PDF-1.4")
    # a pdf whose yaml is not in the call is refused, and nothing is published
    out = run_publish(tmp_path, "testplans", str(plan), str(lone))
    assert out.returncode != 0 and "rpi.yaml" in out.stderr
    assert not (tmp_path / "site" / "testplans").exists()
    out = run_publish(tmp_path, "testplans", str(plan), str(pdf))
    assert out.returncode == 0, out.stderr + out.stdout
    folder = tmp_path / "site" / "testplans" / "v2.0.0-alpha1"
    assert (folder / "psc.yaml").is_file() and (folder / "psc.pdf").read_bytes() == b"%PDF-1.4"
    assert not (tmp_path / "site" / "testplans" / "alpha1").exists()
    # the landing page then links it by itself
    assert "Printable version" in (tmp_path / "site" / "testing" / "index.html").read_text(encoding="utf-8")


def test_splash_bar_links_testing_under_the_same_condition(tmp_path):
    assert repo_index.index_testplans(str(tmp_path)) is None
    assert "/testing/" not in repo_index.render_splash(BASE_URL, [])
    generate(tmp_path)
    nav = repo_index.render_splash(BASE_URL, []).split("</header>")[0]
    assert '<a href="/testing/">Testing</a><a href="https://github.com/autobleem2">GitHub</a>' in nav


def test_task_page_give_it_back_is_a_secondary_link_and_the_date_is_locale_free(tmp_path):
    repo, _ = generate(tmp_path)
    page = read(repo, "testing", "psc.html")
    assert "el('a','dl quiet','Give it back')" in page and "el('button','dl quiet'" not in page
    assert "toLocaleDateString" not in page and "function stamp(d)" in page and "'Oct'" in page
    assert "+'&k=result'" in page


def test_thanks_page_words_a_test_result_and_an_issue_differently(tmp_path):
    repo, _ = generate(tmp_path)
    page = read(repo, "testing", "thanks.html")
    assert 'id="keep"' in page and "look your report up" in page            # the default is the issue wording
    assert "qs('k')==='result'" in page and "we have your test result" in page and "look your result up" in page
    assert "report.html" not in page and "k=result" not in read(repo, "testing", "report.html")
