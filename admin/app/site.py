"""The site's channels (read from its own catalogs on disk) and the builders' health (the runners, the build
server's disk, the build image)."""
import json
import os
import shutil


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def channel_summary(catalog):
    if not catalog:
        return None
    return {
        "version": catalog.get("version"),
        "date": catalog.get("date"),
        "packages": sorted((catalog.get("files") or {}).keys()),
        "images": sorted((catalog.get("images") or {}).keys()),
    }


def channels(repo_dir):
    """what each channel offers now - as the launcher's update check and the installers see it"""
    release = _read(os.path.join(repo_dir, "releases", "latest.json"))
    testing = _read(os.path.join(repo_dir, "releases", "unstable.json"))
    nightly = _read(os.path.join(repo_dir, "nightly", "latest.json"))
    # latest.json is the newest stable, else the pre-release: a pre-release there is not the release channel
    if release and release.get("prerelease"):
        release = None
    images = {}
    for name in ("release", "testing"):
        pc = _read(os.path.join(repo_dir, "pc", "images", name + ".json"))
        if pc:
            images[name] = pc.get("version")
    return {"release": channel_summary(release), "testing": channel_summary(testing),
            "nightly": channel_summary(nightly), "pc_images": images}


def disk(path):
    try:
        u = shutil.disk_usage(path)
        return {"path": path, "total": u.total, "free": u.free, "used_pct": round(100 * u.used / u.total, 1)}
    except OSError as e:
        return {"path": path, "error": str(e)}


class Health:
    def __init__(self, gh, settings):
        self.gh, self.settings = gh, settings

    def runners(self):
        def ask():
            data = self.gh.call("GET", "/orgs/%s/actions/runners?per_page=50" % self.settings.org)
            return [{"name": r["name"], "status": r["status"], "busy": r["busy"],
                     "labels": [l["name"] for l in r.get("labels", [])]} for r in data.get("runners", [])]
        return self.gh.cached("runners", 30, ask)

    def image(self):
        def ask():
            versions = self.gh.call("GET", "/orgs/%s/packages/container/autobleem-build/versions?per_page=20"
                                    % self.settings.org)
            tags = {}
            for v in versions:
                for t in (v.get("metadata", {}).get("container", {}).get("tags") or []):
                    if t in ("develop", "latest") and t not in tags:
                        tags[t] = v.get("updated_at")
            return tags
        return self.gh.cached("image", 300, ask)

    def report(self):
        out = {"disk": disk(self.settings.repo_dir)}
        for name, fn in (("runners", self.runners), ("image", self.image)):
            try:
                out[name] = fn()
            except Exception as e:
                out[name] = {"error": str(e)}
        return out
