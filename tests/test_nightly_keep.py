"""repo_index.py's nightly retention (PLATFORM-10): the site keeps only the single newest nightly build.

Before PLATFORM-10, nightly_folders_to_keep() kept up to two extra older folders as a fallback, so that the
launcher's update (packages) and Imager's nightly list (images) were never left pointing at nothing while the
newest folder was still missing one or the other. That fallback predates the `--partial` + `.incomplete`
marker mechanism (autobleem-appliance's assemble.yml): a folder is never de-marked and indexed until the
whole run - packages and images together - is already in it, so the newest non-incomplete folder always has
both, and the fallback only wasted disk. It is gone now: the newest is kept, everything else under nightly/
goes, whether or not it looks "complete" on its own.
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


#*******************************
# nightly_folders_to_keep(): the unit-level rule
#*******************************

def test_only_the_newest_is_kept():
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"]) == ["c"]
    assert repo_index.nightly_folders_to_keep(["a"]) == ["a"]
    assert repo_index.nightly_folders_to_keep([]) == []


def test_an_incomplete_newest_package_set_is_no_longer_a_reason_to_keep_an_older_one():
    # PLATFORM-10: the newest folder having no packages of its own used to pull in the newest older one that
    # did. Not any more - only the newest folder itself survives, packages or not (a folder without packages
    # can only be the newest by mistake, since publish-nightly never indexes one until it has them).
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"]) == ["c"]


def test_an_incomplete_newest_image_set_is_no_longer_a_reason_to_keep_an_older_one():
    # Same rule for images - previously the fallback would have kept "b" too if "c" had no images yet.
    assert repo_index.nightly_folders_to_keep(["a", "b", "c"]) == ["c"]


#*******************************
# index_nightly(): the full retention + re-index, against a fake site tree
#*******************************

def test_only_the_newest_kept_on_disk_and_in_the_index(tmp_path):
    """PLATFORM-10's known case: the same launcher build (...gbb50426) published on two different nights,
    each with a different component-fingerprint suffix (assemble.yml's `-n<hash>`) - -n863960 the older
    night, -n829217 the newer one. Two genuinely different folders, not one version stored twice (see the
    module comment in repo_index.py) - but PLATFORM-10 still wants only the single newest of the three folders
    below left standing after a re-index, and nothing under nightly/, latest.json, os_list-nightly.json or the
    rendered page naming either of the two pruned ones."""
    repo = str(tmp_path)
    oldest = "v2.0.0-alpha2-350-gabc1234-n111111"
    older_dup = "v2.0.0-alpha2-367-gbb50426-n863960"
    newer_dup = "v2.0.0-alpha2-367-gbb50426-n829217"

    build_nightly_folder(repo, oldest, when=1000)
    build_nightly_folder(repo, older_dup, when=2000)
    build_nightly_folder(repo, newer_dup, when=3000, imager_template=True)

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
