"""The site's addresses: the splash at /, the listing and the manuals under /repository/, stubs at the old
addresses, the links between them - and that no data path moved."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"
TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def nightly_build(date="2026-09-30 03:12 UTC", files=True):
    return {"version": "v2.0.0-alpha0-5-gabc1234", "channel": "dev", "date": date,
            "files": {"psc": {"name": "x"}} if files else {}, "images": {}, "other_files": []}


def test_splash_has_the_status_rows_the_download_button_and_the_kofi_button():
    page = repo_index.render_splash(BASE_URL, [nightly_build()])
    assert "<h1>AutoBleem 2 is coming</h1>" in page
    assert "v2.0.0-alpha0" in page and "First preview tagged" in page
    assert "Next milestone" in page and "alpha1" in page
    # the next milestone is not reached yet: the amber ring, no pill colour
    assert '<span class="dot next"></span><span class="k">Next milestone' in page
    assert '<span class="dot"></span><span class="k">First preview tagged' in page
    assert "last one 30 Sep 2026" in page and '<span class="chan dev">running</span>' in page
    assert '<a class="big" href="/repository/">Download early builds</a>' in page
    assert 'href="https://ko-fi.com/autobleem"' in page and 'rel="noopener"' in page
    assert '<a class="brand" href="/">' in page
    assert BASE_URL + "/assets/og.png" in page
    assert "Red Hat Text" in page and "Selawik" not in page


def test_splash_without_a_kofi_url_has_no_support_button(monkeypatch):
    monkeypatch.setattr(repo_index, "KOFI_URL", "")
    page = repo_index.render_splash(BASE_URL, [])
    assert 'class="support"' not in page
    assert "button-support.png\"" not in page


def test_splash_nightly_row_is_paused_without_a_nightly_and_uses_the_newest_with_packages():
    page = repo_index.render_splash(BASE_URL, None)
    assert '<span class="chan">paused</span>' in page
    older = nightly_build("2026-09-29 03:00 UTC")
    newest_images_only = nightly_build("2026-10-01 03:00 UTC", files=False)
    page = repo_index.render_splash(BASE_URL, [older, newest_images_only])
    assert "last one 29 Sep 2026" in page
    # only images so far: that build is the newest there is
    page = repo_index.render_splash(BASE_URL, [newest_images_only])
    assert "last one 1 Oct 2026" in page


def test_splash_status_comes_from_the_list(monkeypatch):
    monkeypatch.setattr(repo_index, "SPLASH_STATUS", [("Beta", "soon", "pre", "v9")])
    page = repo_index.render_splash(BASE_URL, [])
    assert "Beta" in page and "v9" in page and "First preview tagged" not in page


def test_moved_stub_refreshes_and_links_to_the_repository_copy():
    stub = repo_index.render_moved("rpi-install.html")
    assert '<meta http-equiv="refresh" content="0; url=/repository/rpi-install.html">' in stub
    assert '<a href="/repository/rpi-install.html">' in stub


def test_inner_pages_link_the_listing_not_the_splash():
    head = repo_index.page_head("t", "tag")
    assert '<a class="brand" href="/">' in head
    assert 'href="/repository/#manuals"' in head
    assert "Red Hat Text" in repo_index.PAGE_CSS
    rpi = repo_index.render_rpi_install(BASE_URL, [])
    pc = repo_index.render_pc_install(BASE_URL, [])
    store = repo_index.render_store(BASE_URL, {"psc": []})
    for page in (rpi, pc, store):
        assert '<a href="/repository/">&larr; Downloads</a>' in page
        assert '<a href="/">&larr; Downloads</a>' not in page
    assert "theme: ab2.0.0" in rpi and "theme: ab2.0.0" in store
    assert 'href="/repository/">downloads</a>' in rpi
    listing = repo_index.render_index(BASE_URL, [], [], [], [], [], [], [])
    assert 'href="/repository/rpi-install.html"' in listing and 'href="/repository/pc-install.html"' in listing
    for old in ('href="/rpi-install.html"', 'href="/pc-install.html"'):
        assert old not in listing


def test_the_generator_writes_the_new_layout_and_leaves_the_data_paths_alone(tmp_path):
    repo = str(tmp_path)
    os.makedirs(os.path.join(repo, "store"))
    subprocess.run([sys.executable, os.path.join(TOOLS, "repo_index.py"), repo, "--base-url", BASE_URL],
                   check=True, capture_output=True)
    for name in ("index.html", "repository/index.html", "repository/rpi-install.html",
                 "repository/pc-install.html", "rpi-install.html", "pc-install.html", "store/index.html"):
        assert os.path.isfile(os.path.join(repo, name)), name
    read = lambda n: open(os.path.join(repo, n), encoding="utf-8").read()  # noqa: E731
    assert "AutoBleem 2 is coming" in read("index.html")
    assert "refresh" in read("rpi-install.html") and "refresh" in read("pc-install.html")
    assert "<table" in read("repository/index.html") or "<nav class=\"tabs\"" in read("repository/index.html")
    assert not os.path.exists(os.path.join(repo, "repository", "releases"))
    assert not [n for n in os.listdir(os.path.join(repo, "repository")) if n.startswith(".")]


def test_assets_are_staged_from_the_checked_in_set(tmp_path):
    out = str(tmp_path / "assets")
    subprocess.run([sys.executable, os.path.join(TOOLS, "repo_assets.py"), out], check=True, capture_output=True)
    names = set(os.listdir(out))
    css = repo_index.PAGE_CSS
    # every /assets/ file the pages' CSS and heads name is staged
    wanted = set(re.findall(r"/assets/([A-Za-z0-9@._-]+)", css))
    wanted |= {"emblem.png", "emblem@2x.png", "logo.png", "logo@2x.png", "icon.png", "og.png",
               "button-support.png", "button-support@2x.png", "OFL.txt"}
    assert wanted <= names, wanted - names


def test_the_icon_links_carry_the_icons_hash_and_the_favicon_is_staged(tmp_path):
    import hashlib
    icon = os.path.join(TOOLS, "site-assets", "icon.png")
    assert hashlib.sha1(open(icon, "rb").read()).hexdigest()[:8] == repo_index.ICON_REV
    for page in (repo_index.render_splash(BASE_URL, []), repo_index.page_head("t", "tag")):
        assert 'href="/assets/icon.png?v=%s"' % repo_index.ICON_REV in page
        assert 'href="/favicon.ico?v=%s"' % repo_index.ICON_REV in page
    out = str(tmp_path / "assets")
    subprocess.run([sys.executable, os.path.join(TOOLS, "repo_assets.py"), out], check=True, capture_output=True)
    assert open(os.path.join(out, "favicon.ico"), "rb").read(4) == b"\x00\x00\x01\x00"


def test_the_framed_boxes_use_one_ring_and_the_support_hover_keeps_its_box():
    css = repo_index.PAGE_CSS
    assert "box-shadow:inset 0 0 0 1px" not in css  # the old frames that lost an edge
    assert "polygon(evenodd" in css
    assert "a.support:hover img{content:" not in css  # the hover picture was squeezed into the 252x48 box
    assert "a.support:after" in css and "width:272px;height:68px" in css
