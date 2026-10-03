"""A point release of a pre-release (v2.0.0-alpha1.1, a fix before alpha2) orders between its number and the next:
v2.0.0-alpha1 < v2.0.0-alpha1.1 < v2.0.0-alpha1.2 < v2.0.0-alpha2 (and the same for beta and rc) - in the site's
version key, in what the index keeps and offers, and in the milestone the splash names next."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"
ORDER = ["v1.9.9", "v2.0.0-pre0-933bd2f", "v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-alpha1.2", "v2.0.0-alpha1.10",
         "v2.0.0-alpha2", "v2.0.0-alpha10", "v2.0.0-alpha10.1", "v2.0.0-beta1", "v2.0.0-beta1.1", "v2.0.0-rc1",
         "v2.0.0-rc1.1", "v2.0.0"]


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")


def test_version_key_orders_the_point_between_its_number_and_the_next():
    assert sorted(reversed(ORDER), key=repo_index.version_key) == ORDER


def test_pcsx_key_orders_the_point_too():
    order = ["v2.0.0-alpha1", "v2.0.0-alpha1.1", "v2.0.0-alpha1.9", "v2.0.0-alpha1.10", "v2.0.0-alpha2",
             "v2.0.0-beta1", "v2.0.0-rc1", "v2.0.0-rc1.1", "v2.0.0"]
    assert sorted(reversed(order), key=repo_index.pcsx_version_key) == order


def test_next_milestone_after_a_point_is_the_next_number():
    assert repo_index.next_milestone("v2.0.0-alpha1.1") == "alpha2"
    assert repo_index.next_milestone("v2.0.0-rc2.3") == "rc3"
    assert repo_index.next_milestone("v2.0.0-alpha1") == "alpha2"


def test_the_point_is_the_newest_pre_release_and_alpha1_is_pruned_not_alpha1_1(tmp_path):
    repo = str(tmp_path)
    for tag in ("v2.0.0-alpha1", "v2.0.0-alpha1.1"):
        touch(os.path.join(repo, "releases", tag, "AutoBleemInstaller-%s.zip" % tag))

    releases = repo_index.index_releases(repo, BASE_URL)

    assert not os.path.exists(os.path.join(repo, "releases", "v2.0.0-alpha1"))
    assert os.path.isdir(os.path.join(repo, "releases", "v2.0.0-alpha1.1"))
    assert [r["version"] for r in releases] == ["v2.0.0-alpha1.1"]
    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == "v2.0.0-alpha1.1"


def test_alpha2_stays_above_a_point_of_alpha1(tmp_path):
    repo = str(tmp_path)
    for tag in ("v2.0.0-alpha1.1", "v2.0.0-alpha2"):
        touch(os.path.join(repo, "releases", tag, "AutoBleemInstaller-%s.zip" % tag))

    repo_index.index_releases(repo, BASE_URL)

    assert os.path.isdir(os.path.join(repo, "releases", "v2.0.0-alpha2"))
    assert not os.path.exists(os.path.join(repo, "releases", "v2.0.0-alpha1.1"))


def test_a_file_of_the_point_is_not_a_file_of_its_number():
    assert repo_index.of_version("AutoBleemInstaller-v2.0.0-alpha1.1.zip", "v2.0.0-alpha1.1")
    assert not repo_index.of_version("AutoBleemInstaller-v2.0.0-alpha1.1.zip", "v2.0.0-alpha1")
    assert not repo_index.of_version("AutoBleemInstaller-v2.0.0-alpha1.zip", "v2.0.0-alpha1.1")
