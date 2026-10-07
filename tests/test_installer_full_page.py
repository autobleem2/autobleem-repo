"""PLATFORM-23: AutoBleemInstaller-<v>-full.zip, the installer with the packs it would download beside it (~1 GB, no
BIOS file). The index tells it from the small online installer, a release folder keeps both, unstable.json (the
console's update list) never carries it, and the download page lists it beside the installer with its own line."""
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


def test_the_full_installer_is_its_own_kind_and_the_online_one_stays_installer():
    assert kind_of("AutoBleemInstaller-v2.0.0-alpha1.1-full.zip") == "installer-full"
    assert kind_of("AutoBleemInstaller-v2.0.0-alpha1.1-14-g9f1ad6a3-nd3ef67-full.zip") == "installer-full"
    assert kind_of("AutoBleemInstaller-v2.0.0-alpha1.1.zip") == "installer"
    assert kind_of("AutoBleemInstaller-v2.0.0-alpha1.1-14-g9f1ad6a3-nd3ef67.zip") == "installer"
    # the stick zips are untouched
    assert kind_of("autobleem-psc-v2.0.0-alpha1.1-full.zip") == "psc-full"


def test_a_release_folder_keeps_both_installers(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha1.1")
    for name in ("AutoBleemInstaller-v2.0.0-alpha1.1.zip", "AutoBleemInstaller-v2.0.0-alpha1.1-full.zip",
                 "autobleem-psc-v2.0.0-alpha1.1.tar.gz"):
        touch(os.path.join(root, name))
    # an older release's full installer in the folder is listed, never offered as this release's
    touch(os.path.join(root, "AutoBleemInstaller-v2.0.0-alpha1-full.zip"))

    releases = repo_index.index_releases(repo, BASE_URL)

    files = releases[0]["files"]
    assert files["installer"]["name"] == "AutoBleemInstaller-v2.0.0-alpha1.1.zip"
    assert files["installer-full"]["name"] == "AutoBleemInstaller-v2.0.0-alpha1.1-full.zip"
    assert "AutoBleemInstaller-v2.0.0-alpha1-full.zip" in [o["name"] for o in releases[0]["other_files"]]


def test_unstable_json_never_carries_the_full_installer(tmp_path):
    repo = str(tmp_path)
    root = os.path.join(repo, "releases", "v2.0.0-alpha2")
    for name in ("AutoBleemInstaller-v2.0.0-alpha2.zip", "AutoBleemInstaller-v2.0.0-alpha2-full.zip",
                 "autobleem-psc-v2.0.0-alpha2.tar.gz"):
        touch(os.path.join(root, name))

    repo_index.index_releases(repo, BASE_URL)

    with open(os.path.join(repo, "releases", "unstable.json"), encoding="utf-8") as f:
        unstable = json.load(f)
    assert "installer-full" not in unstable["files"]
    assert "installer" in unstable["files"]
    with open(os.path.join(root, "release.json"), encoding="utf-8") as f:
        assert {"installer", "installer-full", "psc-fs"} <= set(json.load(f)["files"])


def test_the_download_page_lists_the_full_installer_with_its_line(tmp_path):
    repo = str(tmp_path)
    version = "v2.0.0-alpha1.1-14-g9f1ad6a3-nd3ef67"
    folder = os.path.join(repo, "nightly", version)
    for name in ("AutoBleemInstaller-%s.zip", "AutoBleemInstaller-%s-full.zip", "autobleem-psc-%s.tar.gz"):
        touch(os.path.join(folder, name % version))
    with open(os.path.join(folder, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"sources": "x", "images": False, "platforms": "psc"}, f)

    nightly = repo_index.index_nightly(repo, BASE_URL)
    page = repo_index.render_index(BASE_URL, [], [], [], [], [], [], [], nightly=nightly)

    assert nightly[0]["files"]["installer-full"]["name"] == "AutoBleemInstaller-%s-full.zip" % version
    assert "/nightly/%s/AutoBleemInstaller-%s-full.zip" % (version, version) in page
    assert "/nightly/%s/AutoBleemInstaller-%s.zip" % (version, version) in page
    assert "Installer for Windows, everything in the download" in page
    assert "only the BIOS files, if you tick them, come from the internet" in page
    # beside the other installer in the Install panel, not in the folded build inputs
    first_inputs = page.index("<details class=\"inputs\">")
    assert page.index("-full.zip") < first_inputs
