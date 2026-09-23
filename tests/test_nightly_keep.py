"""repo_index.py's nightly retention: the newest build, and an older one only while the newest has no images."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402


def keep(folders, with_images):
    return repo_index.nightly_folders_to_keep(folders, lambda f: f in with_images)


def test_only_the_newest():
    assert keep(["a", "b", "c"], {"a", "b", "c"}) == ["c"]


def test_older_images_kept_until_the_newest_has_its_own():
    assert keep(["a", "b", "c"], {"a", "b"}) == ["b", "c"]
    assert keep(["a", "b", "c"], set()) == ["c"]
    assert keep([], set()) == []


def test_packages_kept_until_the_newest_has_its_own():
    # the newest has one image so far (the image jobs publish first), the one before has everything
    packages = {"a", "b"}
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], lambda f: f in {"a", "b", "c"},
                                              lambda f: f in packages) == ["b", "c"]
    # both pieces missing from the newest: the newest older one with each - here the same folder, once
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], lambda f: f in {"a", "b"},
                                              lambda f: f in packages) == ["b", "c"]
    # the newest complete: only it
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], lambda f: True, lambda f: True) == ["c"]
