"""repo_index.py's index_store: the AutoBleem Store's catalog.json per platform, from the item descriptors."""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)


def item(path, **fields):
    write(path, json.dumps(fields))


def test_catalog_from_descriptors_with_sums_urls_and_pruning():
    with tempfile.TemporaryDirectory() as repo:
        psc = os.path.join(repo, "store", "psc")
        write(os.path.join(psc, "opentyrian-psc-2.1.zip"), b"zip bytes")
        write(os.path.join(psc, "opentyrian-psc-2.0.zip"), b"the old one")  # no descriptor names it
        write(os.path.join(psc, "opentyrian.png"), b"png")
        item(os.path.join(psc, "opentyrian.item.json"), id="app/opentyrian", kind="app", title="OpenTyrian",
             version="2.1", licence="GPL-2.0", image="opentyrian.png", requires=["pack/psc-libs"],
             files=[{"name": "opentyrian-psc-2.1.zip"}])
        write(os.path.join(psc, "hb-d1.chd"), b"disc one")
        write(os.path.join(psc, "hb-d2.chd"), b"disc two")
        item(os.path.join(psc, "homebrew.item.json"), id="ps1/HB-00001", kind="ps1", title="Homebrew",
             files=[{"name": "hb-d1.chd", "disc": 1}, {"name": "hb-d2.chd", "disc": 2}])
        item(os.path.join(psc, "broken.item.json"), id="app/broken", kind="app", title="Broken",
             files=[{"name": "not-there.zip"}])
        item(os.path.join(psc, "untitled.item.json"), id="app/x", kind="app", files=[{"name": "hb-d1.chd"}])

        counts = repo_index.index_store(repo, "https://site")
        assert counts == {"psc": 2}
        with open(os.path.join(psc, "catalog.json"), encoding="utf-8") as f:
            catalog = json.load(f)
        assert catalog["schema"] == 1
        assert catalog["platform"] == "psc"
        by_id = {i["id"]: i for i in catalog["items"]}
        assert set(by_id) == {"app/opentyrian", "ps1/HB-00001"}

        app = by_id["app/opentyrian"]
        assert app["image"] == "https://site/store/psc/opentyrian.png"
        assert app["requires"] == ["pack/psc-libs"]
        assert app["files"] == [{"name": "opentyrian-psc-2.1.zip", "size": 9,
                                 "sha256": hashlib.sha256(b"zip bytes").hexdigest(),
                                 "url": "https://site/store/psc/opentyrian-psc-2.1.zip"}]
        assert [f["disc"] for f in by_id["ps1/HB-00001"]["files"]] == [1, 2]

        # the previous version went; what is named stays
        assert not os.path.exists(os.path.join(psc, "opentyrian-psc-2.0.zip"))
        assert os.path.exists(os.path.join(psc, "opentyrian-psc-2.1.zip"))
        assert os.path.exists(os.path.join(psc, "opentyrian.png"))


def test_pe_item_carries_licence_and_source_url_and_never_the_source_archive():
    with tempfile.TemporaryDirectory() as repo:
        psc = os.path.join(repo, "store", "psc")
        write(os.path.join(psc, "openlara-0.9.0-1.mod"), b"!<arch>\nmod bytes")
        write(os.path.join(psc, "openlara-0.9.0-1-source.tar.gz"), b"source bytes")
        item(os.path.join(psc, "openlara.item.json"), id="pe/openlara", kind="pe", title="OpenLara",
             version="0.9.0-1", licence="BSD-2-Clause",
             source_url="https://site/source/openlara/openlara-0.9.0-1-source.tar.gz",
             files=[{"name": "openlara-0.9.0-1.mod"}])
        item(os.path.join(psc, "badlink.item.json"), id="pe/badlink", kind="pe", title="Bad link",
             source_url="javascript:alert(1)", files=[{"name": "openlara-0.9.0-1.mod"}])
        # a descriptor that lists the source archive among the files is left out whole
        item(os.path.join(psc, "withsource.item.json"), id="pe/withsource", kind="pe", title="With source",
             files=[{"name": "openlara-0.9.0-1.mod"}, {"name": "openlara-0.9.0-1-source.tar.gz"}])

        repo_index.index_store(repo, "https://site")
        with open(os.path.join(psc, "catalog.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        assert set(by_id) == {"pe/openlara", "pe/badlink"}
        pe = by_id["pe/openlara"]
        assert pe["kind"] == "pe" and pe["licence"] == "BSD-2-Clause"
        assert pe["source_url"] == "https://site/source/openlara/openlara-0.9.0-1-source.tar.gz"
        assert [f["name"] for f in pe["files"]] == ["openlara-0.9.0-1.mod"]
        assert "source_url" not in by_id["pe/badlink"]  # not an http(s) address: dropped


def test_store_page_shows_each_system_with_its_items():
    with tempfile.TemporaryDirectory() as repo:
        rpi = os.path.join(repo, "store", "rpi")
        write(os.path.join(rpi, "terminal-rpi-1.0.0.zip"), b"zip bytes")
        write(os.path.join(rpi, "terminal.png"), b"png")
        item(os.path.join(rpi, "terminal.item.json"), id="app/terminal", kind="app", title="Terminal",
             version="1.0.0", author="AutoBleem team", licence="GPL-3.0-or-later", description="A <shell>",
             image="terminal.png", files=[{"name": "terminal-rpi-1.0.0.zip"}])
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        assert pages["rpi"][0]["files"][0]["uploaded"]  # the day it went up, for the Date column

        page = repo_index.render_store("https://site", pages)
        assert "<title>AutoBleem Store</title>" in page
        assert "Terminal" in page and "A &lt;shell&gt;" in page  # escaped
        assert "AutoBleem team &middot; GPL-3.0-or-later" in page
        assert "https://site/store/rpi/terminal.png" in page  # the icon
        assert "https://site/store/rpi/terminal-rpi-1.0.0.zip" in page
        assert "https://site/store/rpi/catalog.json" in page
        assert "https://site/store/psc/catalog.json" not in page  # no catalog there: no dead link
        assert "Nothing for this system yet." in page  # the console's tab
        assert 'data-tab="psc"' in page and 'data-subtab="rpi64"' in page
        assert "Windows" not in page  # nothing for it: no tab

        # the landing page points at it
        landing = repo_index.render_index("https://site", [], {}, {}, {}, [], {}, None, store=pages)
        assert 'href="/store/"' in landing


def test_item_category_is_the_package_type_in_the_catalog_and_on_the_page():
    with tempfile.TemporaryDirectory() as repo:
        psc = os.path.join(repo, "store", "psc")
        write(os.path.join(psc, "doom-psc-1.zip"), b"zip")
        write(os.path.join(psc, "term-psc-1.zip"), b"zip")
        write(os.path.join(psc, "odd-psc-1.zip"), b"zip")
        write(os.path.join(psc, "lara-1.mod"), b"mod")
        item(os.path.join(psc, "doom.item.json"), id="app/doom", kind="app", title="Doom", category="Games",
             files=[{"name": "doom-psc-1.zip"}])
        item(os.path.join(psc, "term.item.json"), id="app/term", kind="app", title="Term", category="tools",
             author="Us", files=[{"name": "term-psc-1.zip"}])
        item(os.path.join(psc, "odd.item.json"), id="app/odd", kind="app", title="Odd", category="pe-apps",
             files=[{"name": "odd-psc-1.zip"}])  # not a package type: dropped, the item stays
        item(os.path.join(psc, "lara.item.json"), id="pe/lara", kind="pe", title="Lara", category="games",
             files=[{"name": "lara-1.mod"}])
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        with open(os.path.join(psc, "catalog.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        assert by_id["app/doom"]["category"] == "games"  # any case in, lower case out
        assert by_id["app/term"]["category"] == "tools"
        assert "category" not in by_id["app/odd"]
        assert by_id["pe/lara"]["category"] == "games"
        page = repo_index.render_store("https://site", pages)
        assert "Type: Games" in page and "Us &middot; Type: Tools" in page
        assert page.count("Type: ") == 3  # the unknown one shows none


def test_no_store_folder():
    with tempfile.TemporaryDirectory() as repo:
        assert repo_index.index_store(repo, "https://site") == {}


def test_uses_provides_requires_reach_the_catalog_and_the_page():
    with tempfile.TemporaryDirectory() as repo:
        psc = os.path.join(repo, "store", "psc")
        for name in ("eng-1.mod", "data-1.mod", "liero-1.zip"):
            write(os.path.join(psc, name), b"x")
        item(os.path.join(psc, "eng.item.json"), id="pe/eng", kind="pe", title="Engine", category="games",
             uses=["Q3-OpenArena ", "bad kind", "q3-openarena", 3], requires=["pe/data"], files=[{"name": "eng-1.mod"}])
        item(os.path.join(psc, "data.item.json"), id="pe/data", kind="pe", title="The data", category="packages",
             files=[{"name": "data-1.mod"}])
        item(os.path.join(psc, "dos.item.json"), id="pe/dos", kind="pe", title="Dos", uses=["dos-game"],
             files=[{"name": "eng-1.mod"}])
        item(os.path.join(psc, "liero.item.json"), id="pkg/liero", kind="package", title="Liero", category="packages",
             provides=["dos-game"], files=[{"name": "liero-1.zip"}])
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        with open(os.path.join(psc, "catalog.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        assert by_id["pe/eng"]["uses"] == ["q3-openarena"]  # trimmed, lower case, junk and repeats dropped
        assert by_id["pe/eng"]["requires"] == ["pe/data"]
        assert by_id["pe/data"]["category"] == "packages" and "uses" not in by_id["pe/data"]
        assert by_id["pkg/liero"]["kind"] == "package" and by_id["pkg/liero"]["provides"] == ["dos-game"]
        page = repo_index.render_store("https://site", pages)
        assert "Needs: The data" in page  # a requirement is named by its title
        assert "Needs game data: dos-game" in page  # no requires: the hint
        assert "Content: dos-game" in page and "Game data packages" in page and "Type: Game data" in page
        assert page.count("Needs game data") == 1  # the engine with a requirement does not repeat it
