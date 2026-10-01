"""channels.json: the release channels the PC Installer and the Flasher list (PLATFORM-20). It sits at the site's
root next to the channels' own jsons, lists a channel only when its json exists, stable first, and leaves the
jsons themselves alone (the updaters read them)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import repo_index  # noqa: E402


def put(repo, path, data):
    full = os.path.join(repo, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(data, f)


def read(repo):
    with open(os.path.join(repo, "channels.json"), encoding="utf-8") as f:
        return json.load(f)


def test_every_channel_with_a_json_is_listed_stable_first(tmp_path):
    repo = str(tmp_path)
    put(repo, "releases/latest.json", {"version": "v2.0.0"})
    put(repo, "releases/unstable.json", {"version": "v2.1.0-alpha1"})
    put(repo, "nightly/latest.json", {"version": "v2.1.0-alpha1-3-gabc1234"})
    put(repo, "preview/latest.json", {"version": "preview-feature-ab-gui-a880c7"})
    put(repo, "pc/images/release.json", {"version": "v2.0.0"})
    put(repo, "pc/images/testing.json", {"version": "v2.1.0-alpha1"})
    repo_index.write_channels(repo)
    data = read(repo)
    assert data["version"] == 1
    assert data["channels"] == [
        {"id": "release", "label": "Release", "index": "releases/latest.json", "unstable": False,
         "images": "pc/images/release.json"},
        {"id": "testing", "label": "Testing", "index": "releases/unstable.json", "unstable": False,
         "images": "pc/images/testing.json"},
        {"id": "nightly", "label": "Nightly", "index": "nightly/latest.json", "unstable": True},
        {"id": "preview", "label": "Preview (feature-ab-gui)", "index": "preview/latest.json", "unstable": True},
    ]


def test_a_channel_without_its_json_is_not_listed_and_images_only_when_they_exist(tmp_path):
    repo = str(tmp_path)
    put(repo, "releases/latest.json", {"version": "v2.0.0"})
    put(repo, "preview/latest.json", {"version": "something-else"})
    repo_index.write_channels(repo)
    channels = read(repo)["channels"]
    assert [c["id"] for c in channels] == ["release", "preview"]
    assert "images" not in channels[0]
    assert channels[1]["label"] == "Preview"  # a version that is not preview-<branch>-<hash>


def test_no_channel_at_all_removes_a_stale_file(tmp_path):
    repo = str(tmp_path)
    put(repo, "releases/latest.json", {"version": "v2.0.0"})
    repo_index.write_channels(repo)
    assert os.path.isfile(os.path.join(repo, "channels.json"))
    os.remove(os.path.join(repo, "releases", "latest.json"))
    assert repo_index.write_channels(repo) == []
    assert not os.path.exists(os.path.join(repo, "channels.json"))


def test_the_channels_own_jsons_are_left_as_they_were(tmp_path):
    repo = str(tmp_path)
    body = {"version": "v2.0.0", "files": {"psc-fs": {"name": "x"}}}
    put(repo, "releases/latest.json", body)
    repo_index.write_channels(repo)
    with open(os.path.join(repo, "releases", "latest.json"), encoding="utf-8") as f:
        assert json.load(f) == body
