"""APPS-8 step 4: the Store page's "PE Apps" section, the source mirror source/<id>/ and the build-dependency
mirror deps/<name>/ (publish kinds pe-source and deps; neither is ever pruned by the nightly cleanup)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import repo_index  # noqa: E402

SOURCE_URL = "https://site/source/commanderkeen/commanderkeen-2.4.0-1-source.tar.gz"


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def pe_repo(repo):
    psc = os.path.join(repo, "store", "psc")
    write(os.path.join(psc, "commanderkeen-2.4.0-1.mod"), b"mod bytes")
    write(os.path.join(psc, "commanderkeen.item.json"), json.dumps({
        "id": "pe/commanderkeen", "kind": "pe", "title": "Commander Genius (Keen 1)", "version": "2.4.0-1",
        "author": "Gerstrong and contributors", "licence": "GPL-2.0", "description": "Plays <Commander Keen>.",
        "source_url": SOURCE_URL, "files": [{"name": "commanderkeen-2.4.0-1.mod"}]}))
    write(os.path.join(psc, "opentyrian-psc-2.1.zip"), b"zip")
    write(os.path.join(psc, "opentyrian.item.json"), json.dumps({
        "id": "app/opentyrian", "kind": "app", "title": "OpenTyrian", "version": "2.1", "licence": "GPL-2.0",
        "files": [{"name": "opentyrian-psc-2.1.zip"}]}))


def test_pe_apps_section_shows_name_version_licence_source_and_the_mod():
    with tempfile.TemporaryDirectory() as repo:
        pe_repo(repo)
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        page = repo_index.render_store("https://site", pages)
    assert "<h2>PE Apps</h2>" in page
    assert "Commander Genius (Keen 1)" in page
    assert '<span class="chan rel">2.4.0-1</span>' in page
    assert "Licence: GPL-2.0" in page
    assert '<a href="%s">Source code</a>' % SOURCE_URL in page
    assert "Plays &lt;Commander Keen&gt;." in page  # escaped
    # the .mod itself, for a manual install into Mods/
    assert 'href="https://site/store/psc/commanderkeen-2.4.0-1.mod"' in page
    assert "<code>Mods/</code>" in page
    # the source archive is a link, never a row of the downloads
    assert "-source.tar.gz</a></td>" not in page
    # the 2020 environment is never named
    for word in ("modmyclassic", "Mod My Classic", "2020"):
        assert word not in page
    # an ordinary App stays in its own section, and the PE App is not in it
    apps = page.split("<h2>Apps</h2>")[1].split("</table>")[0]
    assert "OpenTyrian" in apps and "Commander" not in apps


def test_no_pe_item_no_pe_section():
    with tempfile.TemporaryDirectory() as repo:
        write(os.path.join(repo, "store", "psc", "a.zip"), b"zip")
        write(os.path.join(repo, "store", "psc", "a.item.json"), json.dumps({
            "id": "app/a", "kind": "app", "title": "A", "files": [{"name": "a.zip"}]}))
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        assert "PE Apps</h2>" not in repo_index.render_store("https://site", pages)


def test_pe_item_without_source_url_has_no_source_link():
    with tempfile.TemporaryDirectory() as repo:
        pe_repo(repo)
        path = os.path.join(repo, "store", "psc", "commanderkeen.item.json")
        d = json.load(open(path))
        del d["source_url"]
        write(path, json.dumps(d))
        pages = {}
        repo_index.index_store(repo, "https://site", pages)
        assert "Source code" not in repo_index.render_store("https://site", pages)


def run_index(repo):
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "repo_index.py"), repo, "--base-url", "https://site"],
                   check=True, capture_output=True)


def test_a_full_index_run_leaves_source_and_deps_alone():
    """the nightly cleanup's last step is this run: the GPL source archives (kept 3 years) and the mirrored build
    dependencies must survive it, and the Store page must be written with the PE section"""
    with tempfile.TemporaryDirectory() as repo:
        pe_repo(repo)
        files = {
            "source/commanderkeen/commanderkeen-2.3.0-1-source.tar.gz": b"old source",  # an earlier release stays
            "source/commanderkeen/commanderkeen-2.4.0-1-source.tar.gz": b"source",
            "source/commanderkeen/commanderkeen-2.4.0-1-source.tar.gz.sha256": "abc  x\n",
            "deps/boost/boost_1_74_0.tar.bz2": b"boost",
            "deps/boost/boost_1_74_0.tar.bz2.sha256": "def  x\n",
        }
        for rel, data in files.items():
            write(os.path.join(repo, rel), data)
        run_index(repo)
        run_index(repo)
        for rel, data in files.items():
            with open(os.path.join(repo, rel), "rb" if isinstance(data, bytes) else "r") as f:
                assert f.read() == data, rel
        with open(os.path.join(repo, "store", "index.html"), encoding="utf-8") as f:
            assert "PE Apps</h2>" in f.read()


def test_cleanup_workflow_and_script_never_touch_source_or_deps():
    """cleanup.yml runs server_cleanup.sh (docker only) and then the index run; neither names the site's tree for
    deletion, and the script says why source/ and deps/ are not its business"""
    with open(os.path.join(ROOT, ".github", "workflows", "cleanup.yml"), encoding="utf-8") as f:
        yml = f.read()
    with open(os.path.join(ROOT, "tools", "server_cleanup.sh"), encoding="utf-8") as f:
        script = f.read()
    for text in (yml, script):
        code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        body = "\n".join(code)
        assert "source/" not in body and "deps/" not in body
        assert "AB_REPO_DIR/" not in body.replace("$AB_REPO_DIR:$AB_REPO_DIR", "")
        assert "rm -rf" not in body and "find " not in body and "-delete" not in body
    assert "source/" in script and "deps/" in script  # the comment that keeps the next editor from adding one
    assert "source/" in yml


BASH = shutil.which("bash")


def publish(repo, *args):
    env = dict(os.environ, REPO_DIR=repo, AB_REPO_URL="https://site")
    return subprocess.run([BASH, os.path.join(ROOT, "tools", "repo_publish.sh"), "--local", *args], env=env,
                          capture_output=True, text=True, cwd=ROOT)


@pytest.mark.skipif(not BASH, reason="needs bash")
def test_publish_pe_source_lands_where_the_source_txt_points_and_deps_in_deps():
    with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as repo:
        archive = os.path.join(work, "commanderkeen-2.4.0-1-source.tar.gz")
        boost = os.path.join(work, "boost_1_74_0.tar.bz2")
        other = os.path.join(work, "commanderkeen-2.4.0-1.mod")
        for p in (archive, boost, other):
            write(p, b"x")
        r = publish(repo, "pe-source", "commanderkeen", archive)
        assert r.returncode == 0, r.stderr
        # mkmod.py: AB_SOURCE_BASE (https://.../source) / <id> / <id>-<version>-source.tar.gz
        assert os.path.isfile(os.path.join(repo, "source", "commanderkeen", os.path.basename(archive)))
        assert os.path.isfile(os.path.join(repo, "source", "commanderkeen", os.path.basename(archive) + ".sha256"))
        r = publish(repo, "deps", "boost", boost)
        assert r.returncode == 0, r.stderr
        assert os.path.isfile(os.path.join(repo, "deps", "boost", "boost_1_74_0.tar.bz2"))
        # a file that is not <id>-<version>-source.tar.gz (the .mod, another port's archive) is refused
        r = publish(repo, "pe-source", "commanderkeen", other)
        assert r.returncode != 0 and "not a source archive" in r.stderr
        r = publish(repo, "pe-source", "openjazz", archive)
        assert r.returncode != 0
