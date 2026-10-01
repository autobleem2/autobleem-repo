"""repo_index.py's nightly retention (PLATFORM-10): the site keeps only the single newest nightly build -
plus, while that newest build is only a partial one, the newest older FULL build (PLATFORM-10 review).

Before PLATFORM-10, nightly_folders_to_keep() kept up to two extra older folders as a fallback, so that the
launcher's update (packages) and Imager's nightly list (images) were never left pointing at nothing while the
newest folder was still missing one or the other. That per-piece fallback predates the `--partial` +
`.incomplete` marker mechanism (autobleem-appliance's assemble.yml): a folder is never de-marked and indexed
until the whole run is already in it, so the newest non-incomplete folder normally has everything that run
built, and the old fallback only wasted disk.

But "everything that run built" is not always everything there is: assemble.yml's workflow_dispatch can
legitimately publish a run with only some platforms, or with `images: false`. review found that removing the
fallback outright would then let index_nightly() prune the last FULL nightly the moment such a partial run
lands, leaving the rpi/pcusb launchers' update and Imager's nightly list pointing at nothing for whatever the
partial run left out. So the newest folder is always kept, and while it is only partial (per its
sources.json - nightly_folder_is_full()), the newest older FULL folder is kept alongside it; a normal (full)
night still leaves exactly one folder.
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402

BASE_URL = "https://example.test"


def sha_for(name):
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def touch_with_sidecar(path, when):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")
    sidecar = path + ".sha256"
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (sha_for(os.path.basename(path)), os.path.basename(path)))
    os.utime(sidecar, (when, when))


def build_nightly_folder(repo, version, when, with_package=True, with_image=True, imager_template=False):
    folder = os.path.join(repo, "nightly", version)
    if with_package:
        touch_with_sidecar(os.path.join(folder, "autobleem-psc-%s.tar.gz" % version), when)
    if with_image:
        image_name = "autobleem-%s-rpi-armhf.img.xz" % version
        touch_with_sidecar(os.path.join(folder, image_name), when)
        if imager_template:
            with open(os.path.join(folder, "rpi_imager_repo.json"), "w", encoding="utf-8") as f:
                json.dump({"os_list": [{"name": "AutoBleem", "url": "https://placeholder/img.xz",
                                        "image_download_sha256": sha_for(image_name),
                                        "image_download_size": 1}]}, f)
    return folder


def mark_incomplete(folder):
    open(os.path.join(folder, ".incomplete"), "w").close()


def write_sources(folder, images=True, platforms="rpi-armhf rpi-arm64 pcusb psc win"):
    """publish-nightly's sources.json (assemble.yml): what a run built."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"sources": "deadbeef", "images": images, "platforms": platforms, "run": "x"}, f)


#*******************************
# nightly_folder_is_full(): reads a folder's sources.json the way the plan job's own skip check does
#*******************************

def test_no_sources_json_counts_as_full():
    # predates the images/platforms keys - the plan job's skip check treats it the same way
    assert repo_index.nightly_folder_is_full("/does/not/exist") is True


def test_sources_json_missing_the_keys_counts_as_full(tmp_path):
    folder = str(tmp_path)
    with open(os.path.join(folder, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"sources": "deadbeef", "run": "x"}, f)
    assert repo_index.nightly_folder_is_full(folder) is True


def test_images_false_is_not_full(tmp_path):
    folder = str(tmp_path)
    write_sources(folder, images=False)
    assert repo_index.nightly_folder_is_full(folder) is False


def test_a_platform_subset_is_not_full(tmp_path):
    folder = str(tmp_path)
    write_sources(folder, platforms="psc")
    assert repo_index.nightly_folder_is_full(folder) is False


def test_every_platform_with_images_is_full(tmp_path):
    folder = str(tmp_path)
    write_sources(folder)
    assert repo_index.nightly_folder_is_full(folder) is True


#*******************************
# nightly_folders_to_keep(): the unit-level rule
#*******************************

def test_only_the_newest_is_kept_when_it_is_full():
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], is_full=lambda f: True) == ["c"]
    assert repo_index.nightly_folders_to_keep(["a"], is_full=lambda f: True) == ["a"]
    assert repo_index.nightly_folders_to_keep([], is_full=lambda f: True) == []


def test_a_partial_newest_also_keeps_the_newest_older_full_one():
    # a and b are full, c (the newest) is a workflow_dispatch partial run
    is_full = lambda f: f in {"a", "b"}  # noqa: E731
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], is_full=is_full) == ["b", "c"]


def test_a_partial_newest_with_no_full_older_one_keeps_only_itself():
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], is_full=lambda f: False) == ["c"]


def test_an_incomplete_newest_package_or_image_set_is_no_longer_a_per_piece_fallback_reason():
    # PLATFORM-10: a newest folder missing packages or images used to pull in the newest older one just for
    # that. That per-piece reason is gone - only sources.json's images/platforms decide "full" now, and a
    # finished folder (what index_nightly() ever hands this) always has both.
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"], is_full=lambda f: True) == ["c"]


#*******************************
# index_nightly(): the full retention + re-index, against a fake site tree
#*******************************

def test_only_the_newest_kept_on_disk_and_in_the_index(tmp_path):
    """PLATFORM-10's known case: the same launcher build (...gbb50426) published on two different nights,
    each with a different component-fingerprint suffix (assemble.yml's `-n<hash>`) - -n863960 the older
    night, -n829217 the newer one. Two genuinely different folders, not one version stored twice (see the
    module comment in repo_index.py) - all three folders here are full builds, so only the single newest
    survives a re-index, and nothing under nightly/, latest.json, os_list-nightly.json or the rendered page
    names either of the two pruned ones."""
    repo = str(tmp_path)
    oldest = "v2.0.0-alpha2-350-gabc1234-n111111"
    older_dup = "v2.0.0-alpha2-367-gbb50426-n863960"
    newer_dup = "v2.0.0-alpha2-367-gbb50426-n829217"

    f1 = build_nightly_folder(repo, oldest, when=1000)
    f2 = build_nightly_folder(repo, older_dup, when=2000)
    f3 = build_nightly_folder(repo, newer_dup, when=3000, imager_template=True)
    write_sources(f1)
    write_sources(f2)
    write_sources(f3)

    builds = repo_index.index_nightly(repo, BASE_URL)

    # disk: only the newest folder is left under nightly/ (plus the two json files index_nightly writes there)
    root = os.path.join(repo, "nightly")
    assert sorted(os.listdir(root)) == sorted([newer_dup, "latest.json"])
    assert not os.path.isdir(os.path.join(root, oldest))
    assert not os.path.isdir(os.path.join(root, older_dup))

    # index_nightly()'s own return value
    assert [b["version"] for b in builds] == [newer_dup]

    # nightly/latest.json - the launcher's update check and the installers
    with open(os.path.join(root, "latest.json"), encoding="utf-8") as f:
        latest = json.load(f)
    assert latest["version"] == newer_dup

    # rpi-imager/os_list-nightly.json - Imager's nightly repository
    imager_path = os.path.join(repo, "rpi-imager", "os_list-nightly.json")
    assert os.path.isfile(imager_path)
    with open(imager_path, encoding="utf-8") as f:
        imager_list = json.load(f)
    urls = " ".join(e.get("url", "") for e in imager_list["os_list"])
    assert newer_dup in urls
    assert oldest not in urls
    assert older_dup not in urls

    # the rendered landing page names only the survivor
    page = repo_index.render_index(BASE_URL, [], [], [], [], [], [], [], nightly=builds)
    assert newer_dup in page
    assert oldest not in page
    assert older_dup not in page


def test_a_newest_run_without_images_keeps_the_previous_full_build(tmp_path):
    """workflow_dispatch's `images: false`: the newest folder is a legitimate, complete publish of packages
    only - but it is not a FULL build, so the previous full nightly must stay too (rpi-imager/os_list-nightly
    would otherwise go empty until the next full run)."""
    repo = str(tmp_path)
    previous = "v2.0.0-alpha2-350-gabc1234-n111111"
    packages_only = "v2.0.0-alpha2-360-gcccccc-n222222"

    f_prev = build_nightly_folder(repo, previous, when=1000, imager_template=True)
    f_new = build_nightly_folder(repo, packages_only, when=2000, with_image=False)
    write_sources(f_prev)
    write_sources(f_new, images=False)

    builds = repo_index.index_nightly(repo, BASE_URL)

    assert sorted(b["version"] for b in builds) == sorted([previous, packages_only])
    root = os.path.join(repo, "nightly")
    assert os.path.isdir(os.path.join(root, previous))
    assert os.path.isdir(os.path.join(root, packages_only))

    # Imager's nightly list still points at the previous build's image - not left empty
    imager_path = os.path.join(repo, "rpi-imager", "os_list-nightly.json")
    with open(imager_path, encoding="utf-8") as f:
        imager_list = json.load(f)
    urls = " ".join(e.get("url", "") for e in imager_list["os_list"])
    assert previous in urls

    # the launcher's update check follows the newest build that has packages - the packages-only one
    with open(os.path.join(root, "latest.json"), encoding="utf-8") as f:
        latest = json.load(f)
    assert latest["version"] == packages_only


def test_a_newest_run_with_only_one_platform_keeps_the_previous_full_build(tmp_path):
    """workflow_dispatch's `platforms: psc`: the newest folder only built the console's package, so it is not
    a FULL build either - the previous full nightly must stay for the platforms it did not touch."""
    repo = str(tmp_path)
    previous = "v2.0.0-alpha2-350-gabc1234-n111111"
    psc_only = "v2.0.0-alpha2-361-gdddddd-n333333"

    f_prev = build_nightly_folder(repo, previous, when=1000, imager_template=True)
    f_new = build_nightly_folder(repo, psc_only, when=2000)
    write_sources(f_prev)
    write_sources(f_new, platforms="psc")

    builds = repo_index.index_nightly(repo, BASE_URL)

    assert sorted(b["version"] for b in builds) == sorted([previous, psc_only])
    root = os.path.join(repo, "nightly")
    assert os.path.isdir(os.path.join(root, previous))
    assert os.path.isdir(os.path.join(root, psc_only))


def test_three_full_builds_plus_a_duplicate_pair_leave_exactly_one(tmp_path):
    """The exact PLATFORM-10 disk-full scenario, spelled out as "three full folders, one pair a duplicate
    version" - a normal run of full nightlies always collapses to the single newest, full retention rule or
    not."""
    repo = str(tmp_path)
    oldest = "v2.0.0-alpha2-340-gaaaaaa-n000000"
    older_dup = "v2.0.0-alpha2-367-gbb50426-n863960"
    newer_dup = "v2.0.0-alpha2-367-gbb50426-n829217"

    for version, when in ((oldest, 1000), (older_dup, 2000), (newer_dup, 3000)):
        folder = build_nightly_folder(repo, version, when=when)
        write_sources(folder)

    builds = repo_index.index_nightly(repo, BASE_URL)

    assert [b["version"] for b in builds] == [newer_dup]
    root = os.path.join(repo, "nightly")
    assert sorted(os.listdir(root)) == sorted([newer_dup, "latest.json"])


#*******************************
# unfinished_nightlies(): unchanged by PLATFORM-10 - a build still being published, or abandoned, is a
# separate question from retention among the finished ones
#*******************************

def test_a_build_still_being_published_is_left_alone():
    # b is marked (repo_publish.sh --partial) and got its last file an hour ago; c is marked and was abandoned
    # three days ago; a is a finished nightly
    now = 10 * 24 * 3600
    published = {"a": now - 5 * 24 * 3600, "b": now - 3600, "c": now - 3 * 24 * 3600}
    unfinished, stale = repo_index.unfinished_nightlies(["a", "c", "b"], lambda f: f in {"b", "c"},
                                                        published.get, now)
    assert unfinished == ["b"]
    assert stale == ["c"]
    # nothing marked: nothing held back, nothing removed
    assert repo_index.unfinished_nightlies(["a"], lambda f: False, published.get, now) == ([], [])


def test_a_newer_incomplete_folder_is_never_the_one_kept(tmp_path):
    """A run still being published (--partial, marked .incomplete) is never mistaken for the newest finished
    nightly, even though it is the most recently touched folder on disk - index_nightly() filters it out
    before nightly_folders_to_keep() ever sees it, so the previous, complete nightly stays until the new run's
    last publish takes the marker away."""
    repo = str(tmp_path)
    finished = "v2.0.0-alpha2-350-gabc1234-n111111"
    in_progress = "v2.0.0-alpha2-367-gbb50426-n829217"

    now = time.time()
    build_nightly_folder(repo, finished, when=now - 3600)
    in_progress_folder = build_nightly_folder(repo, in_progress, when=now - 60)
    mark_incomplete(in_progress_folder)

    builds = repo_index.index_nightly(repo, BASE_URL)

    assert [b["version"] for b in builds] == [finished]
    root = os.path.join(repo, "nightly")
    assert os.path.isdir(os.path.join(root, finished))
    # still there, untouched - not yet 2 days old
    assert os.path.isdir(in_progress_folder)


#*******************************
# index_nightly(kind="preview"): a feature branch's build (PLATFORM-20) in preview/, the same rules
#*******************************

def test_a_preview_is_indexed_beside_the_nightly_and_never_touches_it(tmp_path):
    repo = str(tmp_path)
    nightly = build_nightly_folder(repo, "v2.0.0-alpha0-5-gabc1234-n111111", when=1000)
    write_sources(nightly)
    old = "preview-feature-ab-gui-aaaaaa"
    new = "preview-feature-ab-gui-bbbbbb"
    for version, when in ((old, 2000), (new, 3000)):
        folder = os.path.join(repo, "preview", version)
        touch_with_sidecar(os.path.join(folder, "autobleem-psc-%s.zip" % version), when)
        touch_with_sidecar(os.path.join(folder, "autobleem-%s-rpi-armhf.img.xz" % version), when)
        write_sources(folder)
    unfinished = os.path.join(repo, "preview", "preview-feature-x-cccccc")
    touch_with_sidecar(os.path.join(unfinished, "autobleem-psc-preview-feature-x-cccccc.zip"), time.time())
    mark_incomplete(unfinished)

    builds = repo_index.index_nightly(repo, BASE_URL, "preview")

    assert [b["version"] for b in builds] == [new]
    assert builds[0]["channel"] == "preview"
    root = os.path.join(repo, "preview")
    # the older preview pruned, the one still being published left alone
    assert sorted(os.listdir(root)) == sorted([new, "preview-feature-x-cccccc", "latest.json"])
    with open(os.path.join(root, "latest.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == new
    # the nightly is untouched
    assert os.path.isdir(nightly)
    assert not os.path.exists(os.path.join(repo, "nightly", "latest.json"))
