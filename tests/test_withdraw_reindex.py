"""R1 step 3: after `repo_publish.sh withdraw` removes a version's folder, index_releases /
index_pc_images / index_images / index_pcsx must list the newest *remaining* version - not
keep offering the withdrawn one, and not leave a stale latest.json pointing at nothing.

Important finding for whoever runs the actual withdraw/republish sequence (R1-safety.md's
"Order": withdraw alpha2's tools -> republish alpha1 -> withdraw alpha2 from the site): these
indexers already collapse to *one* pre-release folder on every single run (index_releases'
"one pre-release at most", index_images'/index_pc_images' "one pre-release image/PC image set
at most") by keeping the *newest* and pruning the rest - automatically, the moment two
pre-release folders exist side by side. So publishing alpha1 back onto the site *while
alpha2's folder is still there* would have alpha1 auto-pruned again on that very publish's
index run, before `withdraw` ever gets to remove alpha2. The safe order is: withdraw alpha2's
folder completely first (this step's tool), *then* republish alpha1 - never the reverse, and
never both present at once. `test_index_releases_two_prereleases_at_once_keeps_only_the_newest`
below pins that existing auto-prune behaviour down (it is not new code) as a warning fence.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")


def test_index_releases_two_prereleases_at_once_keeps_only_the_newest(tmp_path):
    """Pins the existing auto-prune behaviour: this is why alpha2 must be withdrawn (folder
    removed) BEFORE alpha1 is republished, never the other way round or at the same time."""
    repo = str(tmp_path)
    touch(os.path.join(repo, "releases", "v2.0.0-alpha1", "autobleem-psc-v2.0.0-alpha1.zip"))
    touch(os.path.join(repo, "releases", "v2.0.0-alpha2", "autobleem-psc-v2.0.0-alpha2.zip"))

    repo_index.index_releases(repo, BASE_URL)

    assert not os.path.isdir(os.path.join(repo, "releases", "v2.0.0-alpha1"))  # pruned already
    assert os.path.isdir(os.path.join(repo, "releases", "v2.0.0-alpha2"))


def test_index_releases_lists_the_sole_remaining_prerelease_after_a_withdraw(tmp_path):
    repo = str(tmp_path)
    touch(os.path.join(repo, "releases", "v2.0.0-alpha2", "autobleem-psc-v2.0.0-alpha2.zip"))
    repo_index.index_releases(repo, BASE_URL)
    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == "v2.0.0-alpha2"

    # `repo_publish.sh withdraw release v2.0.0-alpha2` removes the folder outright
    shutil.rmtree(os.path.join(repo, "releases", "v2.0.0-alpha2"))
    repo_index.PUBLISHED_AT.clear()  # a fresh process each publish - repo_publish.sh re-uploads and reruns it
    repo_index.index_releases(repo, BASE_URL)
    assert not os.path.isfile(os.path.join(repo, "releases", "unstable.json"))  # nothing pre-release left

    # only now is alpha1 republished, onto a site with no alpha2 folder at all
    touch(os.path.join(repo, "releases", "v2.0.0-alpha1", "autobleem-psc-v2.0.0-alpha1.zip"))
    repo_index.PUBLISHED_AT.clear()
    repo_index.index_releases(repo, BASE_URL)
    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == "v2.0.0-alpha1"


def test_index_pc_images_testing_json_cleared_after_the_sole_set_is_withdrawn(tmp_path):
    repo = str(tmp_path)
    touch(os.path.join(repo, "pc", "images", "v2.0.0-alpha2", "autobleem-v2.0.0-alpha2-pcusb-i386.img.xz"))
    repo_index.index_pc_images(repo, BASE_URL)
    with open(os.path.join(repo, "pc", "images", "testing.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == "v2.0.0-alpha2"

    shutil.rmtree(os.path.join(repo, "pc", "images", "v2.0.0-alpha2"))
    repo_index.PUBLISHED_AT.clear()
    repo_index.index_pc_images(repo, BASE_URL)
    assert not os.path.isfile(os.path.join(repo, "pc", "images", "testing.json"))

    touch(os.path.join(repo, "pc", "images", "v2.0.0-alpha1", "autobleem-v2.0.0-alpha1-pcusb-i386.img.xz"))
    repo_index.PUBLISHED_AT.clear()
    repo_index.index_pc_images(repo, BASE_URL)
    with open(os.path.join(repo, "pc", "images", "testing.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == "v2.0.0-alpha1"


def test_index_images_os_list_testing_cleared_after_the_sole_set_is_withdrawn(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "rpi-imager", "images")

    def make(version):
        touch(os.path.join(root, version, "autobleem-%s-rpi-armhf.img.xz" % version))
        with open(os.path.join(root, version, "rpi_imager_repo.json"), "w", encoding="utf-8") as f:
            json.dump({"os_list": [{"name": "AutoBleem", "url": "placeholder-armhf.img.xz"}]}, f)

    make("v2.0.0-alpha2")
    repo_index.index_images(repo, BASE_URL)
    with open(os.path.join(repo, "rpi-imager", "os_list-testing.json"), encoding="utf-8") as f:
        entries = json.load(f)["os_list"]
    assert entries and "v2.0.0-alpha2" in entries[0]["url"]

    shutil.rmtree(os.path.join(root, "v2.0.0-alpha2"))
    repo_index.PUBLISHED_AT.clear()
    repo_index.index_images(repo, BASE_URL)
    assert not os.path.isfile(os.path.join(repo, "rpi-imager", "os_list-testing.json"))

    make("v2.0.0-alpha1")
    repo_index.PUBLISHED_AT.clear()
    repo_index.index_images(repo, BASE_URL)
    with open(os.path.join(repo, "rpi-imager", "os_list-testing.json"), encoding="utf-8") as f:
        entries = json.load(f)["os_list"]
    assert entries and "v2.0.0-alpha1" in entries[0]["url"]


def test_index_pcsx_drops_the_stale_latest_json_once_the_sole_build_is_withdrawn(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "emu", "pcsx-ab")
    touch(os.path.join(root, "20260921-bbbbbbb", "pcsx-ab-20260921-bbbbbbb-psc.tar.gz"))

    builds = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
    assert set(builds) == {"20260921-bbbbbbb"}
    assert os.path.isfile(os.path.join(root, "latest.json"))

    # `repo_publish.sh withdraw pcsx-ab 20260921-bbbbbbb` removes the folder; before this fix, a stale
    # latest.json (naming a folder that no longer exists) would survive the next index run untouched
    shutil.rmtree(os.path.join(root, "20260921-bbbbbbb"))
    builds = repo_index.index_pcsx(repo, BASE_URL, name="pcsx-ab")
    assert builds == {}
    assert not os.path.isfile(os.path.join(root, "latest.json"))
