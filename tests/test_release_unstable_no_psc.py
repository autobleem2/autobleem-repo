"""R1 step 5 (R1-safety.md #3): unstable.json must never carry a "psc" file - the console's
update_service.cpp stops at the first channel list that PARSES (it does not check the list actually
has a psc entry), so a psc pre-release named there has no fallback and would offer the same "update"
forever if the console could not apply it, or apply a bad one it could. The fix is data-only:
index_releases() writes a filtered copy to unstable.json while release.json (and everything else
built from the full `releases` list - the download page, InstallerJob::channelRelease) keeps every
file, psc included, so a human can still choose to download a pre-release psc zip on purpose.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")


def test_unstable_json_has_no_psc_file_even_when_the_prerelease_ships_one(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha2")
    touch(os.path.join(root, "autobleem-psc-v2.0.0-alpha2.zip"))
    touch(os.path.join(root, "AutoBleemInstaller-v2.0.0-alpha2.zip"))

    repo_index.index_releases(repo, BASE_URL)

    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        unstable = json.load(f)
    assert "psc" not in unstable["files"]
    assert "installer" in unstable["files"]  # only psc is excluded, not every kind


def test_release_json_and_the_indexed_release_list_still_carry_the_psc_file(tmp_path):
    """The per-folder release.json (what the download page and channelRelease's other lists read)
    and the `releases` list index_releases() returns are untouched - only unstable.json is filtered."""
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha2")
    touch(os.path.join(root, "autobleem-psc-v2.0.0-alpha2.zip"))

    releases = repo_index.index_releases(repo, BASE_URL)

    assert "psc" in releases[0]["files"]
    with open(os.path.join(root, "release.json"), encoding="utf-8") as f:
        assert "psc" in json.load(f)["files"]


def test_unstable_json_is_written_normally_when_the_prerelease_has_no_psc_file(tmp_path):
    """No psc file to begin with (an appliance run that only published PC/Windows kinds) - unstable.json
    still gets written with whatever files the pre-release does have."""
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha2")
    touch(os.path.join(root, "AutoBleemInstaller-v2.0.0-alpha2.zip"))

    repo_index.index_releases(repo, BASE_URL)

    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        unstable = json.load(f)
    assert "psc" not in unstable["files"]
    assert "installer" in unstable["files"]


def test_stable_release_keeps_its_psc_file_in_latest_json(tmp_path):
    """Only unstable.json is filtered - a stable release's latest.json keeps psc, since the safety
    issue (R1-safety.md #3) is specific to the testing channel's one-version-per-list catalog.
    index_releases() only ever calls unstable_view() for the unstable.json branch."""
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0")
    touch(os.path.join(root, "autobleem-psc-v2.0.0.zip"))

    repo_index.index_releases(repo, BASE_URL)

    with open(os.path.join(repo, "releases", "latest.json"), encoding="utf-8") as f:
        assert "psc" in json.load(f)["files"]


def test_unstable_view_returns_the_release_unchanged_when_it_has_no_psc_file():
    release = {"version": "v2.0.0-alpha2", "prerelease": True, "files": {"installer": {"name": "x.zip"}}}
    assert repo_index.unstable_view(release) is release  # no copy needed when nothing is filtered


def test_unstable_view_does_not_mutate_the_release_dict_it_is_given():
    release = {"version": "v2.0.0-alpha2", "prerelease": True,
               "files": {"psc": {"name": "autobleem-psc-v2.0.0-alpha2.zip"}, "installer": {"name": "x.zip"}}}
    view = repo_index.unstable_view(release)
    assert view is not release
    assert "psc" not in view["files"]
    assert "psc" in release["files"]  # the caller's dict (release.json, the releases list) is intact
