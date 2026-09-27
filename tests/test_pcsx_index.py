"""repo_index.py's index_pcsx (emu/<name>/<version>/ for a v* tag build, emu/<name>/nightly/<version>/ for a
develop-push build): the newest build kept per channel (release/testing/nightly), an older one of the same
channel pruned, latest.json mirroring what is kept. RELEASE-4 (channels for the PS1 emulators)."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"


def write(path, data=b"bytes"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def publish(repo, name, version, when, nightly=False, plats=("psc",)):
    """One build's files, published at `when` (the sidecar's mtime is what PUBLISHED_AT/uploaded read)."""
    sub = ("emu", name, "nightly", version) if nightly else ("emu", name, version)
    folder = os.path.join(repo, *sub)
    for plat in plats:
        ext = "zip" if plat == "win64" else "tar.gz"
        path = os.path.join(folder, "%s-%s-%s.%s" % (name, version, plat, ext))
        write(path)
        repo_index.sidecar_sha256(path)
        os.utime(path + ".sha256", (when, when))
    return folder


def setup_function(_func):
    repo_index.PUBLISHED_AT.clear()


def test_release_testing_and_nightly_are_kept_side_by_side():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-abnxt", "v2.0.0", now - 300)
        publish(repo, "pcsx-abnxt", "v2.1.0-alpha1", now - 200)
        publish(repo, "pcsx-abnxt", "r26-31-gabc1234", now - 100, nightly=True)

        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-abnxt")

        assert channels["release"]["version"] == "v2.0.0"
        assert channels["testing"]["version"] == "v2.1.0-alpha1"
        assert channels["nightly"]["version"] == "r26-31-gabc1234"
        f = channels["release"]["files"]["psc"]
        assert f["url"] == "https://example.test/emu/pcsx-abnxt/v2.0.0/pcsx-abnxt-v2.0.0-psc.tar.gz"
        nf = channels["nightly"]["files"]["psc"]
        assert nf["url"] == "https://example.test/emu/pcsx-abnxt/nightly/r26-31-gabc1234/pcsx-abnxt-r26-31-gabc1234-psc.tar.gz"

        with open(os.path.join(repo, "emu", "pcsx-abnxt", "latest.json"), encoding="utf-8") as fh:
            latest = json.load(fh)
        assert set(latest) == {"release", "testing", "nightly"}
        assert latest["nightly"]["version"] == "r26-31-gabc1234"


def test_an_older_nightly_is_pruned_a_newer_one_kept():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-abnxt", "r26-30-gaaaaaaa", now - 200, nightly=True)
        publish(repo, "pcsx-abnxt", "r26-31-gbbbbbbb", now - 100, nightly=True)

        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-abnxt")
        assert channels["nightly"]["version"] == "r26-31-gbbbbbbb"
        assert "release" not in channels and "testing" not in channels

        left = sorted(os.listdir(os.path.join(repo, "emu", "pcsx-abnxt", "nightly")))
        assert left == ["r26-31-gbbbbbbb"]


def test_a_new_release_does_not_touch_the_kept_nightly_or_testing():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-abnxt", "v2.0.0", now - 300)
        publish(repo, "pcsx-abnxt", "v2.1.0-alpha1", now - 200)
        publish(repo, "pcsx-abnxt", "r26-31-gabc1234", now - 100, nightly=True)
        repo_index.index_pcsx(repo, BASE_URL, name="pcsx-abnxt")

        # a newer stable release lands: the nightly and the pre-release channel are untouched
        publish(repo, "pcsx-abnxt", "v2.1.0", now - 50)
        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-abnxt")
        assert channels["release"]["version"] == "v2.1.0"
        assert channels["testing"]["version"] == "v2.1.0-alpha1"
        assert channels["nightly"]["version"] == "r26-31-gabc1234"
        assert not os.path.isdir(os.path.join(repo, "emu", "pcsx-abnxt", "v2.0.0"))  # the old release: pruned
        assert os.path.isdir(os.path.join(repo, "emu", "pcsx-abnxt", "nightly", "r26-31-gabc1234"))


def test_every_platform_file_is_indexed_for_a_channel():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-ab", "v1.0.0", now, plats=("psc", "rpi-armhf", "rpi-arm64", "pcusb", "win64"))
        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
        assert sorted(channels["release"]["files"]) == ["pcusb", "psc", "rpi-arm64", "rpi-armhf", "win64"]


def test_pcsx_ab_and_pcsx_abnxt_are_independent_trees():
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-ab", "20260921-aaaaaaa", now, nightly=True)
        publish(repo, "pcsx-abnxt", "r26-31-gbbbbbbb", now, nightly=True)
        ab = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
        abnxt = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-abnxt")
        assert ab["nightly"]["version"] == "20260921-aaaaaaa"
        assert abnxt["nightly"]["version"] == "r26-31-gbbbbbbb"


def test_legacy_dated_build_directly_under_the_version_folder_is_still_the_nightly_channel():
    """Before the nightly/ subdirectory existed, a manual `repo_publish.sh pcsx <dated-version> ...` put a
    develop-push build straight into emu/<name>/<version>/ - pcsx_channel_of still reads that as nightly, so
    an old site tree upgrades cleanly the first time this runs on it."""
    with tempfile.TemporaryDirectory() as repo:
        now = time.time()
        publish(repo, "pcsx-ab", "20260920-fc8c992", now - 100)  # not nightly=True: straight under emu/pcsx-ab/
        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
        assert channels["nightly"]["version"] == "20260920-fc8c992"

        # a real nightly/ publish afterwards, newer, wins and the legacy folder is pruned
        publish(repo, "pcsx-ab", "20260921-aaaaaaa", now, nightly=True)
        channels = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
        assert channels["nightly"]["version"] == "20260921-aaaaaaa"
        assert not os.path.isdir(os.path.join(repo, "emu", "pcsx-ab", "20260920-fc8c992"))


def test_render_index_draws_the_three_channel_pills_for_the_ps1_emulators_tab():
    channels = {
        "pcsx-abnxt": {
            "release": {"version": "v2.0.0", "files": {"psc": {"name": "pcsx-abnxt-v2.0.0-psc.tar.gz",
                                                                "url": "u", "size": 1, "uploaded": "2026-09-27 00:00 UTC"}}},
            "testing": {"version": "v2.1.0-alpha1", "files": {"psc": {"name": "pcsx-abnxt-v2.1.0-alpha1-psc.tar.gz",
                                                                       "url": "u", "size": 1, "uploaded": "2026-09-27 00:00 UTC"}}},
            "nightly": {"version": "r26-31-gabc1234", "files": {"psc": {"name": "pcsx-abnxt-r26-31-gabc1234-psc.tar.gz",
                                                                        "url": "u", "size": 1, "uploaded": "2026-09-27 00:00 UTC"}}},
        },
    }
    page = repo_index.render_index(BASE_URL, [], {}, {}, {}, [], {}, {}, pcsx=channels)
    assert "PS1 emulators" in page
    assert "<span class=\"chan rel\">v2.0.0</span>" in page
    assert "<span class=\"chan pre\">v2.1.0-alpha1</span>" in page
    assert "<span class=\"chan dev\">dev r26-31-gabc1234</span>" in page
