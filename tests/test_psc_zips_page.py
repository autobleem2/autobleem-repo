"""PLATFORM-21: the PSC release as two stick zips, autobleem-psc-<v>-base.zip (no RetroArch) and -full.zip (with
RetroArch and its cores), neither with a BIOS file. The index tells them apart from the old single zip, a release
folder keeps them, unstable.json (the console's update list) never carries them, and the download page lists them
with a one-line explanation each."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    with open(path + ".sha256", "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (hashlib.sha256(data).hexdigest(), os.path.basename(path)))


def kind_of(name):
    return next((k for k, pattern, _ in repo_index.PACKAGE_KINDS if pattern.match(name)), None)


def test_the_new_zips_are_their_own_kinds_and_the_old_zip_stays_psc():
    assert kind_of("autobleem-psc-v2.0.0-alpha1.1-base.zip") == "psc-base"
    assert kind_of("autobleem-psc-v2.0.0-alpha1.1-full.zip") == "psc-full"
    assert kind_of("autobleem-psc-v2.0.0-alpha1.1-14-g9f1ad6a3-nd3ef67-base.zip") == "psc-base"
    assert kind_of("autobleem-psc-v2.0.0-alpha1.zip") == "psc"
    assert kind_of("autobleem-psc-v2.0.0-alpha1.tar.gz") == "psc-fs"


def test_a_release_folder_keeps_both_zips_and_the_tarball(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha1.1")
    for name in ("autobleem-psc-v2.0.0-alpha1.1-base.zip", "autobleem-psc-v2.0.0-alpha1.1-full.zip",
                 "autobleem-psc-v2.0.0-alpha1.1.tar.gz", "AutoBleemInstaller-v2.0.0-alpha1.1.zip"):
        touch(os.path.join(root, name))
    # another version's zips in the folder are listed, never offered as this release's
    touch(os.path.join(root, "autobleem-psc-v2.0.0-alpha1-base.zip"))

    releases = repo_index.index_releases(repo, BASE_URL)

    files = releases[0]["files"]
    assert files["psc-base"]["name"] == "autobleem-psc-v2.0.0-alpha1.1-base.zip"
    assert files["psc-full"]["name"] == "autobleem-psc-v2.0.0-alpha1.1-full.zip"
    assert files["psc-fs"]["name"] == "autobleem-psc-v2.0.0-alpha1.1.tar.gz"
    assert "autobleem-psc-v2.0.0-alpha1-base.zip" in [o["name"] for o in releases[0]["other_files"]]


def test_unstable_json_never_carries_the_stick_zips(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha2")
    for name in ("autobleem-psc-v2.0.0-alpha2-base.zip", "autobleem-psc-v2.0.0-alpha2-full.zip",
                 "autobleem-psc-v2.0.0-alpha2.tar.gz"):
        touch(os.path.join(root, name))

    repo_index.index_releases(repo, BASE_URL)

    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        unstable = json.load(f)
    assert list(unstable["files"]) == ["psc-fs"]
    with open(os.path.join(root, "release.json"), encoding="utf-8") as f:
        assert {"psc-base", "psc-full", "psc-fs"} <= set(json.load(f)["files"])


def test_the_download_page_lists_both_zips_with_their_line(tmp_path):
    repo = str(tmp_path)
    version = "v2.0.0-alpha1.1-14-g9f1ad6a3-nd3ef67"
    folder = os.path.join(repo, "nightly", version)
    for name in ("autobleem-psc-%s-base.zip", "autobleem-psc-%s-full.zip", "autobleem-psc-%s.tar.gz"):
        touch(os.path.join(folder, name % version))
    with open(os.path.join(folder, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"sources": "x", "images": False, "platforms": "psc"}, f)

    nightly = repo_index.index_nightly(repo, BASE_URL)
    page = repo_index.render_index(BASE_URL, [], [], [], [], [], [], [], nightly=nightly)

    assert nightly[0]["files"]["psc-base"]["name"] == "autobleem-psc-%s-base.zip" % version
    assert "/nightly/%s/autobleem-psc-%s-base.zip" % (version, version) in page
    assert "/nightly/%s/autobleem-psc-%s-full.zip" % (version, version) in page
    assert "AutoBleem without RetroArch, smaller. No BIOS files: add your own." in page
    assert "AutoBleem with RetroArch and its cores. No BIOS files: add your own." in page
    # they sit in the Install panel, not in the folded build inputs
    first_inputs = page.index("<details class=\"inputs\">")
    assert page.index("-base.zip") < first_inputs and page.index("-full.zip") < first_inputs
