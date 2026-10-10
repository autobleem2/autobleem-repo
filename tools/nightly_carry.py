#!/usr/bin/env python3
"""Carry the previous nightly's files of the platforms a run did NOT build into the new nightly folder.

A workflow_dispatch run (or one with a failed platform) publishes only some platforms. Instead of leaving the
new folder without the others, their files are hard-linked (same filesystem: no copy, no extra disk) from the
newest previously published nightly, and sources.json records where each came from:

    "carried": {"<file name>": "<version it was built in>"}

A file the run produced is never overwritten. A full-platform run carries nothing. A file that was itself
carried into the previous folder keeps its original version in "carried".

    nightly_carry.py <nightly-dir> <new-version> <platform,platform,...>
"""
import errno
import json
import os
import re
import shutil
import sys

PLATFORMS = ("rpi-armhf", "rpi-arm64", "pcusb", "psc", "win")

# file name -> platform; the first match wins (rpi-arm64 before the plain rpi pattern's optional -armhf)
PLATFORM_FILES = [
    ("rpi-arm64", re.compile(r"^autobleem-rpi-arm64.*\.tar\.gz$")),
    ("rpi-arm64", re.compile(r"^autobleem-.+-rpi-arm64\.img\.xz$")),
    ("rpi-armhf", re.compile(r"^autobleem-rpi(-armhf)?(-v.*)?\.tar\.gz$")),
    ("rpi-armhf", re.compile(r"^autobleem-.+-rpi-armhf\.img\.xz$")),
    ("pcusb", re.compile(r"^autobleem-pcusb-.*\.tar\.gz$")),
    ("pcusb", re.compile(r"^autobleem-.+-pcusb-i386\.img\.xz$")),
    ("pcusb", re.compile(r"^AutoBleemFlasher-.*\.zip$")),
    ("psc", re.compile(r"^autobleem-psc-.*\.(zip|tar\.gz)$")),
    ("psc", re.compile(r"^AutoBleemInstaller-.*\.zip$")),
    ("win", re.compile(r"^autobleem-win-.*\.zip$")),
    ("win", re.compile(r"^AutoBleemSetup-.*\.exe$")),
    ("win", re.compile(r"^UpdateRoms-.*\.zip$")),
]
# Imager's list template belongs to both Pi image sets: carried when neither Pi platform was built
IMAGER_TEMPLATE = "rpi_imager_repo.json"
PARTIAL_SUFFIX = ".partial"
INCOMPLETE_MARKER = ".incomplete"


def platform_of(name):
    """The platform a data file belongs to, or None (sidecars are handled with their file)."""
    for platform, pattern in PLATFORM_FILES:
        if pattern.match(name):
            return platform
    return None


def files_to_carry(built_platforms, previous_files):
    """The names in `previous_files` (a folder listing) of the platforms NOT in `built_platforms`, each
    followed by its .sha256 sidecar when the listing has one. A run that built every platform carries nothing."""
    built = set(built_platforms)
    if set(PLATFORMS).issubset(built):
        return []
    names = set(previous_files)
    carry = []
    for name in sorted(names):
        platform = platform_of(name)
        wanted = platform is not None and platform not in built
        if name == IMAGER_TEMPLATE:
            wanted = not ({"rpi-armhf", "rpi-arm64"} & built)
        if not wanted:
            continue
        carry.append(name)
        if name + ".sha256" in names:
            carry.append(name + ".sha256")
    return carry


def published_time(folder):
    times = [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder) if n.endswith(".sha256")]
    return max(times) if times else os.path.getmtime(folder)


def finished_nightlies(root, new_version):
    """The finished nightly folders other than `new_version` (not .partial, not .incomplete), newest first."""
    if not os.path.isdir(root):
        return []
    folders = [os.path.join(root, v) for v in os.listdir(root)
               if v != new_version and not v.endswith(PARTIAL_SUFFIX)
               and os.path.isdir(os.path.join(root, v))
               and not os.path.exists(os.path.join(root, v, INCOMPLETE_MARKER))]
    return sorted(folders, key=published_time, reverse=True)


def previous_nightly(root, new_version):
    """The newest finished nightly folder other than `new_version`, or None."""
    folders = finished_nightlies(root, new_version)
    return folders[0] if folders else None


def unit_of(name):
    """What a file is carried for: its platform, or the Imager template (own unit), or None."""
    if name.endswith(".sha256"):
        name = name[:-len(".sha256")]
    return "imager-template" if name == IMAGER_TEMPLATE else platform_of(name)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError as e:
        if e.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK):
            raise
        shutil.copy2(src, dst)


def carry(root, new_version, built_platforms):
    """Link the files into root/new_version; returns {file: from-version}. Never overwrites an existing file."""
    dest = os.path.join(root, new_version)
    if not os.path.isdir(dest):
        return {}
    carried = {}
    done = set()
    # the source is chosen PER PLATFORM: the newest finished folder that has a file of that platform (a newest
    # folder that is package-only or a failed-image leftover must not hide the files of an older one)
    for previous in finished_nightlies(root, new_version):
        prev_sources = read_json(os.path.join(previous, "sources.json"))
        earlier = prev_sources.get("carried") if isinstance(prev_sources.get("carried"), dict) else {}
        found = set()
        for name in files_to_carry(built_platforms, os.listdir(previous)):
            unit = unit_of(name)
            if unit in done:
                continue
            found.add(unit)
            src, dst = os.path.join(previous, name), os.path.join(dest, name)
            if not os.path.isfile(src) or os.path.lexists(dst):
                continue
            link_or_copy(src, dst)
            if not name.endswith(".sha256"):
                carried[name] = earlier.get(name, os.path.basename(previous))
        done |= found
    # read-modify-write of sources.json: this must run AFTER the final upload (which writes the run's own
    # sources.json), never earlier - an earlier run would be overwritten by it and the "carried" record lost
    if carried:
        path = os.path.join(dest, "sources.json")
        data = read_json(path)
        data["carried"] = dict(data.get("carried") or {}, **carried)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return carried


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 1
    root, version, platforms = argv[1], argv[2], [p for p in re.split(r"[,\s]+", argv[3]) if p]
    unknown = [p for p in platforms if p not in PLATFORMS]
    if unknown or not platforms:
        print("nightly_carry: unknown or empty platform list: %s" % argv[3], file=sys.stderr)
        return 1
    carried = carry(root, version, platforms)
    for name in sorted(carried):
        print("carried %s from %s" % (name, carried[name]))
    if not carried:
        print("nothing to carry")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
