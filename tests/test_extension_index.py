"""repo_index.py's index_extensions (extensions/<name>/<version>/) and the Store page's own packages."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402


def write(path, data=b"bytes"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def publish(repo, version, when, names):
    """the files of one build, published at `when` (the sidecar's mtime is the publish time)"""
    folder = os.path.join(repo, "extensions", "store", version)
    for name in names:
        path = os.path.join(folder, name % version)
        write(path)
        repo_index.sidecar_sha256(path)
        os.utime(path + ".sha256", (when, when))


def test_the_newest_release_and_a_newer_development_build_are_kept():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "1.0.0", now - 500, ["ext_store-psc-%s.zip", "abstored-linux-x86_64-%s.tar.gz"])
        publish(repo, "1.1.0", now - 400, ["ext_store-psc-%s.zip", "ext_store-rpi64-%s.zip"])
        publish(repo, "1.1.0-20260920-aaaaaaa", now - 450, ["ext_store-psc-%s.zip"])  # older than 1.1.0: goes
        publish(repo, "1.1.0-20260924-bbbbbbb", now - 100, ["ext_store-psc-%s.zip"])
        publish(repo, "1.1.0-20260923-ccccccc", now - 200, ["ext_store-psc-%s.zip"])  # a newer dev exists: goes
        write(os.path.join(repo, "extensions", "store", "junk", "readme.txt"))  # no package in it: left alone

        out = repo_index.index_extensions(repo, "https://site")
        store = out["store"]
        assert store["release"]["version"] == "1.1.0"
        assert store["development"]["version"] == "1.1.0-20260924-bbbbbbb"
        assert sorted((f["pkg"], f["plat"]) for f in store["release"]["files"]) == \
            [("ext_store", "psc"), ("ext_store", "rpi64")]
        f = store["release"]["files"][0]
        assert f["url"] == "https://site/extensions/store/1.1.0/" + f["name"]

        left = sorted(os.listdir(os.path.join(repo, "extensions", "store")))
        assert left == ["1.1.0", "1.1.0-20260924-bbbbbbb", "junk", "latest.json"]
        with open(os.path.join(repo, "extensions", "store", "latest.json"), encoding="utf-8") as fh:
            assert json.load(fh)["release"]["version"] == "1.1.0"


def test_a_development_build_older_than_the_release_is_dropped():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "1.0.0-20260920-aaaaaaa", now - 300, ["ext_store-psc-%s.zip"])
        publish(repo, "1.0.0", now - 100, ["ext_store-psc-%s.zip"])
        store = repo_index.index_extensions(repo, "https://site")["store"]
        assert store["release"]["version"] == "1.0.0"
        assert "development" not in store


def test_the_store_page_offers_the_extension_and_the_lan_server():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "1.0.0-20260924-bbbbbbb", now, ["ext_store-psc-%s.zip", "ext_store-win-%s.zip",
                                                      "abstored-linux-armhf-%s.tar.gz",
                                                      "abstored-windows-x86_64-%s.zip"])
        extension = repo_index.index_extensions(repo, "https://site")["store"]
        page = repo_index.render_store("https://site", {}, extension)
        assert "The Store itself" in page
        assert "ext_store-psc-1.0.0-20260924-bbbbbbb.zip" in page
        # Windows gets its tab once it has the extension, even with no catalog
        assert "id=\"win\"" in page
        assert "id=\"lanserver\"" in page
        assert "abstored-linux-armhf-1.0.0-20260924-bbbbbbb.tar.gz" in page
        assert "INSTALL-linux.md" in page


def test_the_store_page_without_packages_is_as_before():
    page = repo_index.render_store("https://site", {"psc": []})
    assert "The Store itself" not in page
    assert "lanserver" not in page
    assert "id=\"win\"" not in page
