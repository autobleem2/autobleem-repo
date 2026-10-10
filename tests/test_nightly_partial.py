"""AUTOBLEEM-9: a nightly run that fails or covers only some platforms must never damage a finished nightly
folder. repo_publish.sh --partial stages into nightly/<version>.partial/, repo_index.py never lists or keeps
a .partial folder (and prunes an abandoned one), the run's last publish moves the pieces into place, and
`cleanup-partial` removes only a .partial folder. The fake site tree is built here, in a temp dir."""
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)
import repo_index  # noqa: E402

PUBLISH = os.path.join(TOOLS, "repo_publish.sh")
BASE_URL = "https://example.test"
DAY = 24 * 3600


def put(path, data=b"x", when=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if when is not None:
        os.utime(path, (when, when))


def put_with_sidecar(path, data=b"x", when=None):
    put(path, data, when)
    put(path + ".sha256", ("%s  %s\n" % (hashlib.sha256(data).hexdigest(), os.path.basename(path))).encode(), when)


def finished_nightly(repo, version, when, platforms=("psc", "rpi-armhf")):
    folder = os.path.join(repo, "nightly", version)
    if "psc" in platforms:
        put_with_sidecar(os.path.join(folder, "autobleem-psc-%s.tar.gz" % version), b"psc " + version.encode(), when)
    if "rpi-armhf" in platforms:
        put_with_sidecar(os.path.join(folder, "autobleem-%s-rpi-armhf.img.xz" % version), b"img", when)
    put(os.path.join(folder, "sources.json"), json.dumps({"sources": "x", "images": True,
                                                         "platforms": "rpi-armhf rpi-arm64 pcusb psc win"}).encode(), when)
    return folder


def snapshot(folder):
    state = {}
    for here, _dirs, names in os.walk(folder):
        for n in names:
            p = os.path.join(here, n)
            with open(p, "rb") as f:
                state[os.path.relpath(p, folder)] = (f.read(), os.path.getmtime(p))
    return state


def publish(repo, *args, files=(), env_extra=None):
    env = dict(os.environ, REPO_DIR=repo, AB_REPO_URL=BASE_URL)
    env.update(env_extra or {})
    return subprocess.run(["bash", PUBLISH, "--local"] + list(args) + list(files), env=env,
                          capture_output=True, text=True, timeout=120)


def make_file(tmp_path, name, data=b"new"):
    d = tmp_path / "src"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return str(p)


#*******************************
# repo_index.py: .partial folders
#*******************************

def test_a_partial_folder_is_never_listed_as_a_build(tmp_path):
    repo = str(tmp_path / "site")
    now = time.time()
    finished_nightly(repo, "v2.0.0-alpha2-1-gaaaaaaa", now - 3600)
    put_with_sidecar(os.path.join(repo, "nightly", "v2.0.0-alpha2-2-gbbbbbbb.partial",
                                  "autobleem-psc-v2.0.0-alpha2-2-gbbbbbbb.tar.gz"), when=now - 10)
    builds = repo_index.index_nightly(repo, BASE_URL)
    assert [b["version"] for b in builds] == ["v2.0.0-alpha2-1-gaaaaaaa"]
    assert os.path.isdir(os.path.join(repo, "nightly", "v2.0.0-alpha2-2-gbbbbbbb.partial"))


def test_a_one_platform_folder_keeps_the_previous_full_one_and_ignores_the_partial(tmp_path):
    repo = str(tmp_path / "site")
    now = time.time()
    finished_nightly(repo, "v-1", now - 7200)
    one = finished_nightly(repo, "v-2", now - 3600, platforms=("psc",))
    put(os.path.join(one, "sources.json"), json.dumps({"images": True, "platforms": "psc"}).encode(), now - 3600)
    put_with_sidecar(os.path.join(repo, "nightly", "v-3.partial", "autobleem-psc-v-3.tar.gz"), when=now)
    builds = repo_index.index_nightly(repo, BASE_URL)
    assert sorted(b["version"] for b in builds) == ["v-1", "v-2"]
    assert os.path.isdir(os.path.join(repo, "nightly", "v-3.partial"))


def test_an_abandoned_partial_folder_is_pruned_by_its_newest_file(tmp_path):
    repo = str(tmp_path / "site")
    now = time.time()
    finished_nightly(repo, "v-1", now - 3600)
    old = os.path.join(repo, "nightly", "v-2.partial")
    put_with_sidecar(os.path.join(old, "a.tar.gz"), when=now - 3 * DAY)
    # the folder's own mtime is old too, but one fresh file keeps a staging folder alive
    fresh = os.path.join(repo, "nightly", "v-3.partial")
    put_with_sidecar(os.path.join(fresh, "a.tar.gz"), when=now - 3 * DAY)
    put(os.path.join(fresh, "b.tar.gz"), when=now - 60)
    repo_index.index_nightly(repo, BASE_URL)
    assert not os.path.exists(old)
    assert os.path.isdir(fresh)


def test_the_old_incomplete_marker_on_a_site_folder_still_holds_it_back(tmp_path):
    repo = str(tmp_path / "site")
    now = time.time()
    finished_nightly(repo, "v-1", now - 3600)
    marked = finished_nightly(repo, "v-2", now - 60)
    open(os.path.join(marked, ".incomplete"), "w").close()
    builds = repo_index.index_nightly(repo, BASE_URL)
    assert [b["version"] for b in builds] == ["v-1"]


def test_a_preview_partial_is_ignored_too(tmp_path):
    repo = str(tmp_path / "site")
    put_with_sidecar(os.path.join(repo, "preview", "preview-x-abcdef", "autobleem-psc-preview-x-abcdef.tar.gz"),
                     when=time.time() - 100)
    put_with_sidecar(os.path.join(repo, "preview", "preview-x-abcdee.partial", "autobleem-psc-a.tar.gz"),
                     when=time.time())
    builds = repo_index.index_nightly(repo, BASE_URL, "preview")
    assert [b["version"] for b in builds] == ["preview-x-abcdef"]


#*******************************
# repo_publish.sh --partial --local: a finished folder is never touched
#*******************************

def test_partial_stages_beside_a_finished_folder_and_leaves_it_untouched(tmp_path):
    repo = str(tmp_path / "site")
    version = "v2.0.0-alpha2-5-gabcdef0"
    folder = finished_nightly(repo, version, time.time() - 5000)
    before = snapshot(folder)
    r = publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, "autobleem-win-%s.zip" % version)])
    assert r.returncode == 0, r.stderr
    assert snapshot(folder) == before
    assert not os.path.exists(os.path.join(folder, ".incomplete"))
    staged = os.path.join(repo, "nightly", version + ".partial")
    assert sorted(os.listdir(staged)) == ["autobleem-win-%s.zip" % version, "autobleem-win-%s.zip.sha256" % version]
    # no index ran
    assert not os.path.exists(os.path.join(repo, "nightly", "latest.json"))


def test_a_run_that_never_finishes_leaves_the_site_whole_after_any_later_index(tmp_path):
    repo = str(tmp_path / "site")
    old = "v2.0.0-alpha2-4-g1111111"
    new = "v2.0.0-alpha2-5-g2222222"
    folder = finished_nightly(repo, old, time.time() - 5000)
    before = snapshot(folder)
    for name in ("autobleem-psc-%s.tar.gz" % new, "autobleem-win-%s.zip" % new):
        assert publish(repo, "--partial", "nightly", new, files=[make_file(tmp_path, name)]).returncode == 0
    r = publish(repo, "index")
    assert r.returncode == 0, r.stderr
    # the index only adds its own listing files (release.json, SHA256SUMS); every file of the build is as it was
    after = snapshot(folder)
    assert {k: v for k, v in after.items() if k not in ("release.json", "SHA256SUMS")} == before
    with open(os.path.join(repo, "nightly", "latest.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == old
    assert os.path.isdir(os.path.join(repo, "nightly", new + ".partial"))
    assert not os.path.exists(os.path.join(repo, "nightly", new))


def test_the_final_publish_moves_the_pieces_in_and_merges_over_a_finished_folder(tmp_path):
    repo = str(tmp_path / "site")
    version = "v2.0.0-alpha2-5-gabcdef0"
    folder = finished_nightly(repo, version, time.time() - 5000)
    psc = "autobleem-psc-%s.tar.gz" % version
    win = "autobleem-win-%s.zip" % version
    assert publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, psc, b"rebuilt psc")]).returncode == 0
    assert publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, win, b"win")]).returncode == 0
    sources = make_file(tmp_path, "sources.json", json.dumps({"sources": "y", "images": True,
                                                              "platforms": "rpi-armhf rpi-arm64 pcusb psc win"}).encode())
    r = publish(repo, "nightly", version, files=[sources])
    assert r.returncode == 0, r.stderr
    assert not os.path.exists(os.path.join(repo, "nightly", version + ".partial"))
    names = os.listdir(folder)
    # merged over: the rebuilt package replaced the old one, the image of the earlier run is still there
    assert open(os.path.join(folder, psc), "rb").read() == b"rebuilt psc"
    assert "autobleem-%s-rpi-armhf.img.xz" % version in names
    assert win in names and win + ".sha256" in names
    with open(os.path.join(folder, psc + ".sha256"), encoding="utf-8") as f:
        assert f.read().split()[0] == hashlib.sha256(b"rebuilt psc").hexdigest()
    assert not os.path.exists(os.path.join(folder, ".incomplete"))
    with open(os.path.join(repo, "nightly", "latest.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == version


def test_the_final_publish_of_a_new_version_with_no_partial_still_works(tmp_path):
    repo = str(tmp_path / "site")
    version = "v2.0.0-alpha2-6-g3333333"
    r = publish(repo, "nightly", version, files=[make_file(tmp_path, "autobleem-psc-%s.tar.gz" % version)])
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(os.path.join(repo, "nightly", version, "autobleem-psc-%s.tar.gz" % version))


def test_partial_is_for_development_builds_only(tmp_path):
    r = publish(str(tmp_path / "site"), "--partial", "release", "v1", files=[make_file(tmp_path, "a.zip")])
    assert r.returncode != 0


#*******************************
# repo_publish.sh cleanup-partial
#*******************************

def test_cleanup_partial_removes_only_the_partial_folder(tmp_path):
    repo = str(tmp_path / "site")
    folder = finished_nightly(repo, "v-1", time.time() - 100)
    put_with_sidecar(os.path.join(repo, "nightly", "v-1.partial", "a.tar.gz"))
    put_with_sidecar(os.path.join(repo, "nightly", "v-2.partial", "a.tar.gz"))
    before = snapshot(folder)
    r = publish(repo, "cleanup-partial", "nightly", "v-1")
    assert r.returncode == 0, r.stderr
    assert not os.path.exists(os.path.join(repo, "nightly", "v-1.partial"))
    assert os.path.isdir(os.path.join(repo, "nightly", "v-2.partial"))
    assert snapshot(folder) == before


def test_cleanup_partial_with_nothing_there_is_a_no_op(tmp_path):
    repo = str(tmp_path / "site")
    finished_nightly(repo, "v-1", time.time() - 100)
    r = publish(repo, "cleanup-partial", "nightly", "v-1")
    assert r.returncode == 0, r.stderr
    assert os.path.isdir(os.path.join(repo, "nightly", "v-1"))


def test_cleanup_partial_refuses_anything_that_is_not_a_plain_name(tmp_path):
    repo = str(tmp_path / "site")
    folder = finished_nightly(repo, "v-1", time.time() - 100)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("k")
    before = snapshot(folder)
    for channel, version in (("nightly", "../v-1"), ("..", "v-1"), ("nightly/..", "x"), ("nightly", "v-1/../../x"),
                             ("nightly", ""), ("", "v-1"), ("nightly", ".."), ("nightly", "."), (".tools", "x"),
                             ("nightly", "v 1"), ("nightly", "v-1.partial/x"), ("nightly.partial", "v-1"), ("/", "x")):
        r = publish(repo, "cleanup-partial", channel, version)
        assert r.returncode != 0, (channel, version)
    assert snapshot(folder) == before
    assert (victim / "keep").read_text() == "k"
    assert publish(repo, "cleanup-partial", "nightly").returncode != 0


def test_cleanup_partial_refuses_a_symlinked_partial_and_deletes_nothing(tmp_path):
    repo = str(tmp_path / "site")
    folder = finished_nightly(repo, "v-1", time.time() - 100)
    os.symlink(folder, os.path.join(repo, "nightly", "v-9.partial"))
    r = publish(repo, "cleanup-partial", "nightly", "v-9")
    assert r.returncode != 0
    assert os.path.isfile(os.path.join(folder, "sources.json"))


#*******************************
# the final publish: the merge happens only after the final upload
#*******************************

def test_a_failed_final_upload_leaves_the_partial_folder_and_the_nightly_untouched(tmp_path):
    repo = str(tmp_path / "site")
    version = "v2.0.0-alpha2-7-g4444444"
    folder = finished_nightly(repo, version, time.time() - 5000)
    win = "autobleem-win-%s.zip" % version
    assert publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, win, b"win")]).returncode == 0
    partial = os.path.join(repo, "nightly", version + ".partial")
    before_partial, before_folder = snapshot(partial), snapshot(folder)
    # the upload (a copy into the site tree) fails: a directory sits where the final sources.json has to go
    os.remove(os.path.join(folder, "sources.json"))
    os.mkdir(os.path.join(folder, "sources.json"))
    before_folder = snapshot(folder)
    r = publish(repo, "nightly", version, files=[make_file(tmp_path, "sources.json", b"{}")])
    assert r.returncode != 0
    assert os.path.isdir(os.path.join(folder, "sources.json"))
    assert snapshot(partial) == before_partial
    assert snapshot(folder) == before_folder


def test_a_staged_file_never_replaces_a_file_of_the_final_set(tmp_path):
    repo = str(tmp_path / "site")
    version = "v2.0.0-alpha2-8-g5555555"
    win = "autobleem-win-%s.zip" % version
    other = "autobleem-psc-%s.tar.gz" % version
    assert publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, win, b"staged win")]).returncode == 0
    assert publish(repo, "--partial", "nightly", version, files=[make_file(tmp_path, other, b"staged psc")]).returncode == 0
    (tmp_path / "final").mkdir()
    final_win = tmp_path / "final" / win
    final_win.write_bytes(b"final win")
    r = publish(repo, "nightly", version, files=[str(final_win)])
    assert r.returncode == 0, r.stderr
    folder = os.path.join(repo, "nightly", version)
    assert open(os.path.join(folder, win), "rb").read() == b"final win"
    with open(os.path.join(folder, win + ".sha256"), encoding="utf-8") as f:
        assert f.read().split()[0] == hashlib.sha256(b"final win").hexdigest()
    assert open(os.path.join(folder, other), "rb").read() == b"staged psc"
    assert not os.path.exists(os.path.join(repo, "nightly", version + ".partial"))


def test_a_symlinked_stale_partial_does_not_stop_the_index(tmp_path):
    repo = str(tmp_path / "site")
    finished_nightly(repo, "v2.0.0-alpha2-9-g6666666", time.time() - 5000)
    target = tmp_path / "elsewhere"
    put(str(target / "keep.txt"), b"keep", time.time() - 10 * DAY)
    link = os.path.join(repo, "nightly", "v2.0.0-alpha2-10-g7777777.partial")
    os.symlink(str(target), link)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "repo_index.py"), repo, "--base-url", BASE_URL],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert os.path.islink(link)
    assert (target / "keep.txt").read_bytes() == b"keep"
