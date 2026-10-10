"""AUTOBLEEM-9 C: the platforms a nightly run did not build are carried (hard-linked) from the previous nightly."""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)
import nightly_carry  # noqa: E402

ALL = ["rpi-armhf", "rpi-arm64", "pcusb", "psc", "win"]
PUBLISH = os.path.join(TOOLS, "repo_publish.sh")


def names_for(v):
    return {
        "rpi-armhf": ["autobleem-rpi-armhf-%s.tar.gz" % v, "autobleem-%s-rpi-armhf.img.xz" % v],
        "rpi-arm64": ["autobleem-rpi-arm64-%s.tar.gz" % v, "autobleem-%s-rpi-arm64.img.xz" % v],
        "pcusb": ["autobleem-pcusb-i386-%s.tar.gz" % v, "autobleem-%s-pcusb-i386.img.xz" % v],
        "psc": ["autobleem-psc-%s-base.zip" % v, "autobleem-psc-%s-full.zip" % v, "AutoBleemInstaller-%s.zip" % v],
        "win": ["AutoBleemSetup-%s.exe" % v, "autobleem-win-%s.zip" % v, "UpdateRoms-%s.zip" % v],
    }


def build(root, version, platforms, when, sources=None):
    folder = os.path.join(root, version)
    os.makedirs(folder, exist_ok=True)
    for p in platforms:
        for n in names_for(version)[p]:
            for name in (n, n + ".sha256"):
                with open(os.path.join(folder, name), "w") as f:
                    f.write(name)
                os.utime(os.path.join(folder, name), (when, when))
    if "rpi-armhf" in platforms:
        with open(os.path.join(folder, "rpi_imager_repo.json"), "w") as f:
            f.write("{}")
    with open(os.path.join(folder, "sources.json"), "w") as f:
        json.dump(sources or {"sources": "s", "images": True, "platforms": " ".join(platforms)}, f)
    return folder


#*******************************
# files_to_carry(): the pure function
#*******************************

def test_a_full_platform_run_carries_nothing():
    listing = [n for p in ALL for n in names_for("v1")[p]]
    assert nightly_carry.files_to_carry(ALL, listing) == []


def test_a_subset_carries_the_files_of_the_other_platforms_with_their_sidecars():
    listing = []
    for p in ALL:
        for n in names_for("v1")[p]:
            listing += [n, n + ".sha256"]
    got = nightly_carry.files_to_carry(["psc", "win"], listing)
    expected = []
    for p in ("rpi-armhf", "rpi-arm64", "pcusb"):
        for n in names_for("v1")[p]:
            expected += [n, n + ".sha256"]
    assert sorted(got) == sorted(expected)


def test_the_imager_template_is_carried_only_when_no_pi_platform_was_built():
    listing = ["rpi_imager_repo.json", "autobleem-v1-rpi-armhf.img.xz"]
    assert "rpi_imager_repo.json" in nightly_carry.files_to_carry(["psc"], listing)
    assert "rpi_imager_repo.json" not in nightly_carry.files_to_carry(["rpi-arm64"], listing)


def test_unknown_files_are_never_carried():
    assert nightly_carry.files_to_carry(["psc"], ["SHA256SUMS", "release.json", "sources.json", "notes.txt"]) == []


#*******************************
# carry(): the step, against a fake site tree
#*******************************

def test_carry_hard_links_and_records_the_origin(tmp_path):
    root = str(tmp_path / "nightly")
    old = build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ["psc"], time.time() - 100)
    carried = nightly_carry.carry(root, "v-2", ["psc"])
    assert "AutoBleemSetup-v-1.exe" in carried and carried["AutoBleemSetup-v-1.exe"] == "v-1"
    assert not any("psc" in n for n in carried)
    src, dst = os.path.join(old, "AutoBleemSetup-v-1.exe"), os.path.join(new, "AutoBleemSetup-v-1.exe")
    assert os.path.samefile(src, dst)
    assert os.path.samefile(src + ".sha256", dst + ".sha256")
    with open(os.path.join(new, "sources.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["carried"] == carried and data["platforms"] == "psc"
    # the old folder is untouched
    assert sorted(os.listdir(old)) == sorted(set(os.listdir(old)))
    assert os.path.exists(os.path.join(old, "autobleem-psc-v-1-base.zip"))


def test_carry_never_overwrites_a_file_the_run_produced(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ["psc"], time.time() - 100)
    mine = os.path.join(new, "autobleem-v-1-pcusb-i386.img.xz")  # same name the previous folder has
    with open(mine, "w") as f:
        f.write("produced by this run")
    carried = nightly_carry.carry(root, "v-2", ["psc"])
    assert "autobleem-v-1-pcusb-i386.img.xz" not in carried
    with open(mine) as f:
        assert f.read() == "produced by this run"


def test_a_unit_already_in_the_destination_is_never_carried(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ["rpi-armhf"], time.time() - 100)  # package + image + Imager template
    carried = nightly_carry.carry(root, "v-2", ["psc", "win"])
    assert not any("v-1" in n for n in os.listdir(new) if "armhf" in n)
    assert not os.path.exists(os.path.join(new, "autobleem-rpi-armhf-v-1.tar.gz"))
    assert not os.path.exists(os.path.join(new, "autobleem-v-1-rpi-armhf.img.xz"))
    with open(os.path.join(new, "rpi_imager_repo.json")) as f:
        assert f.read() == "{}"
    expected = set()
    for p in ("rpi-arm64", "pcusb"):
        expected |= set(names_for("v-1")[p])
    assert set(carried) == expected
    assert os.path.exists(os.path.join(new, "autobleem-rpi-arm64-v-1.tar.gz"))


def test_a_full_run_carries_nothing_and_leaves_sources_json_alone(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ALL, time.time() - 100)
    before = open(os.path.join(new, "sources.json")).read()
    assert nightly_carry.carry(root, "v-2", ALL) == {}
    assert open(os.path.join(new, "sources.json")).read() == before
    assert not any("v-1" in n for n in os.listdir(new))


def test_carry_skips_partial_and_incomplete_previous_folders(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 9000)
    marked = build(root, "v-2", ALL, time.time() - 5000)
    open(os.path.join(marked, ".incomplete"), "w").close()
    build(root, "v-3.partial", ALL, time.time() - 4000)
    new = build(root, "v-4", ["psc"], time.time() - 100)
    carried = nightly_carry.carry(root, "v-4", ["psc"])
    assert set(carried.values()) == {"v-1"}
    assert os.path.exists(os.path.join(new, "AutoBleemSetup-v-1.exe"))


def test_a_file_carried_twice_keeps_its_original_version(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 9000)
    build(root, "v-2", ["psc"], time.time() - 5000)
    nightly_carry.carry(root, "v-2", ["psc"])
    build(root, "v-3", ["psc"], time.time() - 100)
    carried = nightly_carry.carry(root, "v-3", ["psc"])
    assert carried["AutoBleemSetup-v-1.exe"] == "v-1"


def test_with_no_previous_nightly_nothing_is_carried(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ["psc"], time.time())
    assert nightly_carry.carry(root, "v-1", ["psc"]) == {}


#*******************************
# repo_publish.sh carry-nightly
#*******************************

def run_publish(repo, *args):
    env = dict(os.environ, REPO_DIR=repo, AB_REPO_URL="https://example.test")
    return subprocess.run(["bash", PUBLISH, "--local"] + list(args), env=env, capture_output=True, text=True, timeout=120)


def test_carry_nightly_kind_carries_then_indexes(tmp_path):
    repo = str(tmp_path / "site")
    root = os.path.join(repo, "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ["psc"], time.time() - 100)
    r = run_publish(repo, "carry-nightly", "v-2", "psc")
    assert r.returncode == 0, r.stderr + r.stdout
    assert os.path.exists(os.path.join(new, "AutoBleemSetup-v-1.exe"))
    with open(os.path.join(new, "sources.json"), encoding="utf-8") as f:
        assert f.read().count("v-1") >= 1
    # the new build is partial (psc only), so the full previous one stays beside it
    assert os.path.isdir(os.path.join(root, "v-1"))
    assert os.path.isfile(os.path.join(new, "release.json"))


def test_carry_nightly_kind_refuses_bad_arguments(tmp_path):
    repo = str(tmp_path / "site")
    assert run_publish(repo, "carry-nightly", "v-2").returncode != 0
    assert run_publish(repo, "carry-nightly", "../x", "psc").returncode != 0
    assert run_publish(repo, "carry-nightly", "v-2", "psc;rm").returncode != 0
    assert run_publish(repo, "carry-nightly", "v-2", "nonsense").returncode != 0


def test_carry_nightly_for_a_missing_version_folder_is_an_error(tmp_path):
    repo = str(tmp_path / "site")
    build(os.path.join(repo, "nightly"), "v-1", ALL, time.time() - 5000)
    r = run_publish(repo, "carry-nightly", "v-9", "psc")
    assert r.returncode != 0
    assert "v-9" in r.stderr + r.stdout
    assert "nothing to carry" not in r.stdout


def test_carry_nightly_with_an_existing_folder_and_nothing_to_carry_exits_zero(tmp_path):
    repo = str(tmp_path / "site")
    build(os.path.join(repo, "nightly"), "v-1", ["psc"], time.time() - 100)
    r = run_publish(repo, "carry-nightly", "v-1", "psc")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "nothing to carry" in r.stdout


def test_carried_files_keep_their_old_version_in_the_name(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    new = build(root, "v-2", ["psc"], time.time() - 100)
    carried = nightly_carry.carry(root, "v-2", ["psc"])
    assert carried
    for name in carried:
        # no renaming: the origin is recorded in sources.json (the unversioned Imager template has no version at all)
        assert "v-2" not in name
        assert "v-1" in name or name == "rpi_imager_repo.json"
        assert os.path.exists(os.path.join(new, name))
    assert "AutoBleemSetup-v-1.exe" in carried


def test_the_final_publish_carries_when_asked(tmp_path):
    repo = str(tmp_path / "site")
    root = os.path.join(repo, "nightly")
    build(root, "v-1", ALL, time.time() - 5000)
    src = tmp_path / "autobleem-psc-v-2-base.zip"
    src.write_bytes(b"psc")
    env = dict(os.environ, REPO_DIR=repo, AB_REPO_URL="https://example.test", AB_CARRY_PLATFORMS="psc")
    r = subprocess.run(["bash", PUBLISH, "--local", "nightly", "v-2", str(src)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout
    assert os.path.exists(os.path.join(root, "v-2", "AutoBleemSetup-v-1.exe"))
    assert os.path.exists(os.path.join(root, "v-2", "autobleem-psc-v-2-base.zip"))


def test_the_source_is_chosen_per_platform_not_from_the_newest_folder_only(tmp_path):
    root = str(tmp_path / "nightly")
    build(root, "v-1", ALL, time.time() - 9000)
    build(root, "v-2", ["psc"], time.time() - 5000)  # newest finished folder: no rpi-armhf files
    new = build(root, "v-3", ["win"], time.time() - 100)
    carried = nightly_carry.carry(root, "v-3", ["win"])
    for n in names_for("v-1")["rpi-armhf"]:
        assert carried[n] == "v-1"
        assert os.path.exists(os.path.join(new, n))
    for n in names_for("v-2")["psc"]:
        assert carried[n] == "v-2"
    with open(os.path.join(new, "sources.json"), encoding="utf-8") as f:
        assert json.load(f)["carried"] == carried
