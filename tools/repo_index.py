#!/usr/bin/env python3
"""Regenerate the machine-readable files and the landing page of the download repository.

Run on the server over the repository directory after every publish (tools/repo_publish.sh does it):

    repo_index.py /home/claude/autobleem-repo --base-url https://autobleem.retromenele.pl

Reads what is there (CLAUDE.md, "The download repository", has the layout) and writes:

    releases/<tag>/release.json        the packages of that release: name, size, sha256, url
    releases/latest.json               the newest stable release's release.json
    releases/unstable.json             the one pre-release kept, same shape
    rpi/retroarch/latest.json          the newest RetroArch build per architecture
    psc/retroarch/latest.json          the newest RetroArch build for the PlayStation Classic (psc/retroarch/<tag>/)
    psc/cores/latest.json              the newest cores tarball for the console (psc/cores/cores-psc-<date>.tar.gz)
    psc/libs/latest.json               the newest runtime-library pack for the console's apps (psc/libs/libs-psc-<date>.tar.gz)
    psc/apps/latest.json               the newest pack of the console's third-party Apps (psc/apps/apps-psc-<date>.tar.gz)
    psc/bios/latest.json               the console's BIOS list (psc/bios/biospack.txt: what the installer fetches from
                                       RetroBIOS into RetroArch/bios - only the list is here, never a BIOS file)
    win/retroarch/<v>/                 RetroArch for the Windows product: libretro's own x86_64 build repacked as
                                       retroarch-win64-<v>.tar.gz (ci/build_retroarch.sh win64), the newest kept,
                                       latest.json = the file plus "version"
    win/cores/                         cores-win64-<date>.tar.gz (ci/build_cores.sh win64), the newest kept
    win/bios/                          biospack-win64.txt, the Windows list (tools/biospack.py --arch win64)
    rpi/cores/latest.json              the newest cores tarball per architecture (rpi/cores/<arch>/)
    samples/latest.json                the newest sample-games pack (samples/samples-<date>.tar.gz, tools/build_samples.py)
    emu/pcsx-ab/latest.json            the newest build of each emulator, one package per platform (emu/<name>/<version>/,
    emu/pcsx-abnxt/latest.json         each repository's tools/make_packages.sh) - the classic pcsx-ab and the next one
    rpi-imager/os_list.json            the newest images' Imager metadata with real urls (from the
                                       rpi_imager_repo.json make_rpi_image.sh wrote next to them)
    index.html                         the landing page
    rpi-install.html                   the Raspberry Pi manual: which image for which Pi, the setup, games
    pc-install.html                    the PC USB stick's manual: what it runs on, writing the stick, the setup

Every file's sha256 comes from its `<name>.sha256` sidecar (sha256sum format) when there is one, else it
is computed and the sidecar written.

Retention (the owner's rule, 2026-09-19): pre-release builds are not kept - a new one replaces the previous
one, in releases/ and in rpi-imager/images/ alike. The page shows the latest stable release and that one
pre-release (its own panel, marked as a development build; unstable.json for machines), and the newest
image set even when it is a pre-release. Of the RetroArch builds only the newest version is kept.
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

# bump on every change: tools/repo_publish.sh only replaces the copy the repository runs with a newer one
INDEX_VERSION = 43

# the release packages, by the name they carry (tools/make_*_package.sh, ci/build.sh)
PACKAGE_KINDS = [
    ("installer", re.compile(r"^AutoBleemInstaller-.*\.zip$"),
     "PlayStation Classic installer for Windows (downloads the stick's file system from the channel picked in it)"),
    ("psc", re.compile(r"^autobleem-psc-.*\.zip$"), "PlayStation Classic (USB stick zip)"),
    ("psc-fs", re.compile(r"^autobleem-psc-.*\.tar\.gz$"),
     "PlayStation Classic, the stick's file system for the installer (no RetroArch and no cover databases - "
     "the installer adds those from the packs below and db/)"),
    ("rpi", re.compile(r"^autobleem-rpi(-armhf)?(-v.*)?\.tar\.gz$"), "Raspberry Pi, 32-bit OS (tarball + install.sh)"),
    ("rpi64", re.compile(r"^autobleem-rpi-arm64.*\.tar\.gz$"), "Raspberry Pi, 64-bit OS (tarball + install.sh)"),
    ("pcusb", re.compile(r"^autobleem-pcusb-i386.*\.tar\.gz$"),
     "PC USB stick, 32-bit Debian (tarball + install.sh - what the stick image installs and updates from)"),
    ("win-setup", re.compile(r"^AutoBleemSetup-.*\.exe$"), "Windows installer (per user, no administrator rights)"),
    ("win-product", re.compile(r"^autobleem-win-product-.*\.zip$"),
     "Windows, the same program as a portable folder (dataroot.txt names the data folder)"),
    ("win", re.compile(r"^autobleem-win-(?!product).*\.zip$"), "Windows (launcher, for a look on a PC)"),
    ("updateroms", re.compile(r"^UpdateRoms-.*\.zip$"), "UpdateRoms for Windows (scan a stick or card on a PC)"),
    ("flasher", re.compile(r"^AutoBleemFlasher-.*\.zip$"),
     "PC USB stick flasher for Windows (downloads the stick image of a channel and writes it)"),
]
IMAGE_RE = re.compile(r"^autobleem-(?P<version>.+)-rpi-(?P<arch>armhf|arm64)\.img\.xz$")
# the PC stick's image (tools/make_pc_image.sh), under pc/images/<version>/
PC_IMAGE_RE = re.compile(r"^autobleem-(?P<version>.+)-pcusb-(?P<arch>i386)\.img\.xz$")
# the appliances' RetroArch builds and cores tarballs, under rpi/ (armhf, arm64) and pc/ (i386)
RETROARCH_RE = re.compile(r"^retroarch-(?P<tag>v[0-9][^-]*)-(?P<arch>armhf|arm64|i386)\.tar\.gz$")
CORES_RE = re.compile(r"^cores-(?P<arch>armhf|arm64|i386)-(?P<date>[0-9]{8})\.tar\.gz$")
PLATFORM_ARCHES = {"rpi": ("armhf", "arm64"), "pc": ("i386",)}
# the console build's tag is the RetroArch version plus a build number (github.com/autobleem/retroarch-psc)
PSC_RETROARCH_RE = re.compile(r"^retroarch-psc-(?P<tag>v[0-9][0-9.]*-[0-9]+)\.zip$")
PSC_CORES_RE = re.compile(r"^cores-psc-(?P<date>[0-9]{8})\.tar\.gz$")
PSC_LIBS_RE = re.compile(r"^libs-psc-(?P<date>[0-9]{8})\.tar\.gz$")
# the Windows product: libretro's own build repacked, its cores, its BIOS list (AutoBleemWinSetup reads them)
WIN_RETROARCH_RE = re.compile(r"^retroarch-win64-(?P<version>[0-9][0-9.]*)\.tar\.gz$")
WIN_CORES_RE = re.compile(r"^cores-win64-(?P<date>[0-9]{8})\.tar\.gz$")
PSC_APPS_RE = re.compile(r"^apps-psc-(?P<date>[0-9]{8})\.tar\.gz$")
# the from-source kernel-flasher payload (boot.img + abrootfs.tgz), PREVIEW - not yet hardware-tested
PSC_KERNEL_RE = re.compile(r"^kernel-psc-(?P<date>[0-9]{8})\.tar\.gz$")
SAMPLES_RE = re.compile(r"^samples-(?P<date>[0-9]{8})\.tar\.gz$")
# the emulators' packages under emu/<name>/<version>/ (each repository's tools/make_packages.sh)
PCSX_RE = re.compile(r"^(?P<name>pcsx-ab|pcsx-abnxt)-(?P<version>.+)-(?P<plat>psc|rpi-armhf|rpi-arm64|pcusb|win64)\.(tar\.gz|zip)$")
EMULATORS = (
    ("pcsx-ab", "pcsx-ab, the classic emulator",
     "The PS1 emulator AutoBleem has always shipped (<code>Autobleem/bin/emu/</code>): PCSX-ReARMed as the console's "
     "firmware took it in 2017, with Sony's and AutoBleem's additions "
     "(<a href=\"https://github.com/autobleem/pcsx-ab2\">github.com/autobleem/pcsx-ab2</a>)."),
    ("pcsx-abnxt", "pcsx-abnxt, the next emulator",
     "The PS1 emulator that replaces pcsx-ab: upstream PCSX-ReARMed as it is today (r26) with the console's "
     "front buttons, the resume points, the in-game menu and the filters on top "
     "(<a href=\"https://github.com/autobleem/pcsx-abnxt\">github.com/autobleem/pcsx-abnxt</a>). The launcher's "
     "Options -> \"PS1 Emulator\" picks it (<code>Autobleem/bin/emunxt/</code>)."),
)
PCSX_PLATFORMS = (("psc", "PlayStation Classic"), ("rpi-armhf", "Raspberry Pi, 32-bit OS"),
                  ("rpi-arm64", "Raspberry Pi, 64-bit OS"), ("pcusb", "PC USB stick (32-bit Linux)"),
                  ("win64", "Windows"))


# version folder -> its mtime, filled in as the tree is read: two builds of the same pre-release label
# (v2.0.0-pre0-933bd2f, v2.0.0-pre0-1ba1e84) differ only by a commit hash, which has no order - the one
# published later is the newer one
PUBLISHED_AT = {}


def version_key(tag):
    """v2.0.0-pre0-933bd2f -> sortable; a tag with a suffix sorts before the same version without one;
    a trailing commit hash is ignored and the publish time decides instead. The pre-release labels rank
    pre < alpha < beta < rc (then their number): v2.0.0-alpha1 is newer than any v2.0.0-pre0-<sha>
    development build, which the plain string order had the other way round (2026-09-21)."""
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-(.*))?$", tag)
    if not m:
        return (0, 0, 0, 0, (0, 0, tag), PUBLISHED_AT.get(tag, 0))
    major, minor, patch, suffix = m.groups()
    label = re.sub(r"-[0-9a-f]{7,40}$", "", suffix or "")
    ranks = {"pre": 0, "alpha": 1, "beta": 2, "rc": 3}
    lm = re.match(r"^(pre|alpha|beta|rc)(\d*)$", label)
    label_key = (ranks[lm.group(1)], int(lm.group(2) or 0), "") if lm else (4, 0, label)
    return (int(major), int(minor), int(patch or 0), 0 if suffix else 1, label_key, PUBLISHED_AT.get(tag, 0))


def note_published(folder):
    PUBLISHED_AT[os.path.basename(folder)] = os.path.getmtime(folder)


def is_prerelease(tag):
    return bool(re.search(r"-(pre|rc|alpha|beta)", tag))


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_sha256(path):
    """The hash from <path>.sha256 (sha256sum format), computed and written when missing."""
    sidecar = path + ".sha256"
    if os.path.isfile(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            first = f.readline().split()
        if first and re.fullmatch(r"[0-9a-f]{64}", first[0]):
            return first[0]
    digest = sha256_of(path)
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(path)))
    return digest


def file_entry(repo, base_url, path):
    rel = os.path.relpath(path, repo).replace(os.sep, "/")
    return {
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "sha256": sidecar_sha256(path),
        "url": base_url + "/" + rel,
        "uploaded": uploaded_at(path),
    }


def uploaded_at(path):
    """When the file was published, UTC: the .sha256 sidecar's mtime - repo_publish.sh writes it as it
    publishes (rsync -t keeps the package's own mtime, which is when it was built) - else the file's."""
    stamp = path + ".sha256"
    when = os.path.getmtime(stamp if os.path.isfile(stamp) else path)
    return datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def data_files(directory):
    """The regular files of a directory that are not sidecars, json or hidden, sorted."""
    if not os.path.isdir(directory):
        return []
    names = sorted(os.listdir(directory))
    return [
        os.path.join(directory, n)
        for n in names
        if os.path.isfile(os.path.join(directory, n))
        and not n.startswith(".")
        and not n.endswith(".sha256")
        and not n.endswith(".json")
        and n != "SHA256SUMS"
    ]


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def prune(folders, keep, what):
    """Delete the folders not in `keep` (a list of version folders), saying which."""
    for folder in folders:
        if folder not in keep and os.path.isdir(folder):
            print("pruning %s %s" % (what, os.path.basename(folder)))
            shutil.rmtree(folder)


def newest_of(versions):
    return sorted(versions, key=version_key)[-1] if versions else None


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.0f %s" % (size, unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%d" % size


#*******************************
# releases
#*******************************
VERSIONED_RE = re.compile(r"-v\d+\.\d+")


def of_version(name, version):
    """Is a package file of this version? A name that carries no version (the oldest packages) is; one that
    does must end in it - "-<version>.<ext>", or "-<version>-<hash>.<ext>" as the old CI named them - which
    tells v2.0.0 from v2.0.0-alpha1 (a prefix match would not)."""
    if not VERSIONED_RE.search(name):
        return True
    return re.search(r"-%s(-[0-9a-f]{7,40})?\.(zip|tar\.gz|exe|img\.xz)$" % re.escape(version), name) is not None


def index_releases(repo, base_url):
    root = os.path.join(repo, "releases")
    releases = []
    if os.path.isdir(root):
        for tag in os.listdir(root):
            if os.path.isdir(os.path.join(root, tag)):
                note_published(os.path.join(root, tag))
        for tag in sorted(os.listdir(root), key=version_key):
            folder = os.path.join(root, tag)
            if not os.path.isdir(folder) or not tag.startswith("v"):
                continue
            files = {}
            others = []
            # two files of one kind in a folder: a package carried over from the previous pre-release and
            # the same kind published for real afterwards (2026-09-21: the Windows set, twice). The newer
            # file is the release's, the older one goes - it was only ever a stand-in
            for path in data_files(folder):
                entry = file_entry(repo, base_url, path)
                if not of_version(entry["name"], tag):
                    # another version's file in this folder (the old pre-release carry-over left alpha1's
                    # Windows set in v2.0.0-alpha2/): kept, listed, never offered as this release's download -
                    # an update would install that other version under this one's name, again and again
                    others.append(entry)
                    continue
                for kind, pattern, _ in PACKAGE_KINDS:
                    if not pattern.match(entry["name"]):
                        continue
                    if kind in files:
                        have = os.path.join(folder, files[kind]["name"])
                        loser = have if os.path.getmtime(have) < os.path.getmtime(path) else path
                        print("dropping %s: superseded (%s)" % (os.path.basename(loser), kind))
                        for suffix in ("", ".sha256"):
                            if os.path.isfile(loser + suffix):
                                os.remove(loser + suffix)
                        if loser == have:
                            files[kind] = entry
                    else:
                        files[kind] = entry
                    break
                else:
                    others.append(entry)
            if not files and not others:
                continue
            with open(os.path.join(folder, "SHA256SUMS"), "w", encoding="utf-8") as f:
                for entry in list(files.values()) + others:
                    f.write("%s  %s\n" % (entry["sha256"], entry["name"]))
            release = {
                "version": tag,
                "prerelease": is_prerelease(tag),
                "date": datetime.fromtimestamp(os.path.getmtime(folder), timezone.utc).strftime("%Y-%m-%d"),
                "files": files,
                "other_files": others,
            }
            write_json(os.path.join(folder, "release.json"), release)
            releases.append(release)
    # one pre-release at most: the newest; every stable release stays. Nothing is carried over from the
    # pre-release it replaces any more (2026-09-23): autobleem-appliance publishes every kind of a release
    # together, and a carried package was another version's file offered under this one's name
    stable = [r for r in releases if not r["prerelease"]]
    pre = [r for r in releases if r["prerelease"]]
    if len(pre) > 1:
        prune([os.path.join(root, r["version"]) for r in pre[:-1]], [], "pre-release")
        pre = pre[-1:]
    for name, which in (("latest.json", stable), ("unstable.json", pre)):
        path = os.path.join(root, name)
        if which:
            write_json(path, which[-1])
        elif os.path.isfile(path):
            os.remove(path)
    return stable + pre


#*******************************
# RetroArch builds
#*******************************
def index_retroarch(repo, base_url, platform="rpi"):
    """<platform>/retroarch/<tag>/retroarch-<tag>-<arch>.tar.gz (ci/build_retroarch.sh) - the newest tag kept,
    latest.json = its entries by architecture; what install.sh and the launcher's update read."""
    root = os.path.join(repo, platform, "retroarch")
    builds = {}  # tag -> arch -> entry
    if os.path.isdir(root):
        for tag in os.listdir(root):
            folder = os.path.join(root, tag)
            if not os.path.isdir(folder):
                continue
            note_published(folder)
            for path in data_files(folder):
                m = RETROARCH_RE.match(os.path.basename(path))
                if m:
                    builds.setdefault(tag, {})[m.group("arch")] = file_entry(repo, base_url, path)
    if builds:
        newest = newest_of(builds)
        prune([os.path.join(root, t) for t in builds if t != newest], [], "RetroArch build")
        builds = {newest: builds[newest]}
        latest = {"version": newest}
        latest.update(builds[newest])
        write_json(os.path.join(root, "latest.json"), latest)
    return builds


#*******************************
# RetroArch for the PlayStation Classic
#*******************************
def psc_version_key(tag):
    """v1.22.2-3 -> ((1, 22, 2), 3): the RetroArch version, then our build number."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)-(\d+)$", tag)
    if not m:
        return ((0, 0, 0), 0, tag)
    return (tuple(int(x) for x in m.groups()[:3]), int(m.group(4)), tag)


def index_psc_retroarch(repo, base_url):
    """psc/retroarch/<tag>/retroarch-psc-<tag>.zip + manifest.json (from the retroarch-psc repository's
    `make package-retroarch`) - the newest kept, the rest deleted, latest.json = the newest."""
    root = os.path.join(repo, "psc", "retroarch")
    builds = {}  # tag -> {"zip": entry, "manifest": url}
    if os.path.isdir(root):
        for tag in os.listdir(root):
            folder = os.path.join(root, tag)
            if not os.path.isdir(folder):
                continue
            for path in data_files(folder):
                m = PSC_RETROARCH_RE.match(os.path.basename(path))
                if m and m.group("tag") == tag:
                    builds[tag] = {"zip": file_entry(repo, base_url, path)}
                    manifest = os.path.join(folder, "manifest.json")
                    if os.path.isfile(manifest):
                        builds[tag]["manifest"] = base_url + "/psc/retroarch/%s/manifest.json" % tag
    if builds:
        newest = sorted(builds, key=psc_version_key)[-1]
        prune([os.path.join(root, t) for t in builds if t != newest], [], "PSC RetroArch build")
        builds = {newest: builds[newest]}
        latest = {"version": newest}
        latest.update(builds[newest])
        write_json(os.path.join(root, "latest.json"), latest)
    return builds


def index_psc_dated(repo, base_url, kind, pattern, what):
    """psc/<kind>/<kind>-psc-<date>.tar.gz (+ <kind>-psc-<date>.json, the list inside) - the newest kept."""
    root = os.path.join(repo, "psc", kind)
    dated = {}
    for path in data_files(root):
        m = pattern.match(os.path.basename(path))
        if m:
            dated[m.group("date")] = path
    if not dated:
        return None
    newest = max(dated)
    for date, path in dated.items():
        if date != newest:
            print("pruning PSC %s %s" % (what, os.path.basename(path)))
            for f in (path, path + ".sha256", os.path.join(root, "%s-psc-%s.json" % (kind, date))):
                if os.path.isfile(f):
                    os.remove(f)
    entry = file_entry(repo, base_url, dated[newest])
    entry["date"] = newest
    manifest = os.path.join(root, "%s-psc-%s.json" % (kind, newest))
    if os.path.isfile(manifest):
        entry["manifest"] = base_url + "/psc/%s/%s-psc-%s.json" % (kind, kind, newest)
        try:
            with open(manifest, encoding="utf-8") as f:
                entry["count"] = json.load(f).get("count")
        except (OSError, ValueError):
            pass
    write_json(os.path.join(root, "latest.json"), entry)
    return entry


def index_psc_cores(repo, base_url):
    """psc/cores/: RetroBoot 1.2's cores as retroarch-psc's tools/pack_retroboot_cores.py packs them."""
    return index_psc_dated(repo, base_url, "cores", PSC_CORES_RE, "cores tarball")


def index_psc_libs(repo, base_url):
    """psc/libs/: the runtime libraries RetroBoot's apps and AutoBleem's Apps need beyond the firmware
    (retroarch-psc's tools/pack_retroboot_libs.py)."""
    return index_psc_dated(repo, base_url, "libs", PSC_LIBS_RE, "library pack")


def index_psc_kernel(repo, base_url):
    """psc/kernel/: the from-source kernel-flasher payload (boot.img + abrootfs.tgz) rebuilt by
    autobleem/psc-kernel-payload, packed by tools/repo_publish.sh psc-kernel as kernel-psc-<date>.tar.gz.
    PREVIEW - not yet booted on a console."""
    return index_psc_dated(repo, base_url, "kernel", PSC_KERNEL_RE, "kernel payload")


def index_psc_bios(repo, base_url):
    """psc/bios/biospack.txt - the console's BIOS manifest (tools/biospack.py --arch psc): one line per file,
    <sha256> <size> <url> <path>, the URLs pointing at RetroBIOS. latest.json says how many files and bytes
    the installer would fetch, and which RetroBIOS commit the list is from."""
    return index_bios_list(repo, base_url, "psc", "biospack.txt")


def index_bios_list(repo, base_url, platform, filename):
    """<platform>/bios/<filename> -> <platform>/bios/latest.json (see index_psc_bios)"""
    path = os.path.join(repo, platform, "bios", filename)
    if not os.path.isfile(path):
        return None
    entry = file_entry(repo, base_url, path)
    count = total = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("# Built by tools/biospack.py"):
                m = re.search(r"at ([0-9a-f]{7,40}),", line)
                if m:
                    entry["retrobios_ref"] = m.group(1)
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split(" ", 3)
            if len(parts) == 4:
                count += 1
                total += int(parts[1])
    entry["count"] = count
    entry["total_bytes"] = total
    write_json(os.path.join(repo, platform, "bios", "latest.json"), entry)
    return entry


#*******************************
# the Windows product
#*******************************
def win_version_key(version):
    return tuple(int(x) for x in re.findall(r"\d+", version)) or (0,)


def index_win(repo, base_url):
    """win/retroarch/<v>/retroarch-win64-<v>.tar.gz (libretro's Windows build repacked - the newest version
    kept, latest.json = its entry plus "version"), win/cores/cores-win64-<date>.tar.gz (the newest kept,
    latest.json = its entry plus "date") and win/bios/biospack-win64.txt (latest.json as for the console)
    - what AutoBleemWinSetup fetches, each falling back to libretro's own servers when missing here."""
    out = {}
    root = os.path.join(repo, "win", "retroarch")
    builds = {}
    if os.path.isdir(root):
        for version in os.listdir(root):
            folder = os.path.join(root, version)
            if not os.path.isdir(folder):
                continue
            note_published(folder)
            for path in data_files(folder):
                m = WIN_RETROARCH_RE.match(os.path.basename(path))
                if m and m.group("version") == version:
                    builds[version] = file_entry(repo, base_url, path)
    if builds:
        newest = max(builds, key=win_version_key)
        prune([os.path.join(root, v) for v in builds if v != newest], [], "Windows RetroArch build")
        entry = dict(builds[newest])
        entry["version"] = newest
        write_json(os.path.join(root, "latest.json"), entry)
        out["retroarch"] = entry
    root = os.path.join(repo, "win", "cores")
    dated = {}
    for path in data_files(root):
        m = WIN_CORES_RE.match(os.path.basename(path))
        if m:
            dated[m.group("date")] = path
    if dated:
        newest = max(dated)
        for date, path in dated.items():
            if date != newest:
                print("pruning cores tarball %s" % os.path.basename(path))
                os.remove(path)
                if os.path.isfile(path + ".sha256"):
                    os.remove(path + ".sha256")
        entry = file_entry(repo, base_url, dated[newest])
        entry["date"] = newest
        write_json(os.path.join(root, "latest.json"), entry)
        out["cores"] = entry
    bios = index_bios_list(repo, base_url, "win", "biospack-win64.txt")
    if bios:
        out["bios"] = bios
    return out


def index_psc_apps(repo, base_url):
    """psc/apps/: the console's third-party Apps (amiberry, doom, eduke32, ...) as tools/pack_psc_apps.py
    packs them - Apps/<name>/ folders, self-contained, laid out for the stick."""
    return index_psc_dated(repo, base_url, "apps", PSC_APPS_RE, "apps pack")


#*******************************
# cores tarballs
#*******************************
def index_cores(repo, base_url, platform="rpi"):
    """<platform>/cores/<arch>/cores-<arch>-<date>.tar.gz - the newest per architecture, the rest deleted."""
    root = os.path.join(repo, platform, "cores")
    latest = {}
    for arch in PLATFORM_ARCHES[platform]:
        folder = os.path.join(root, arch)
        dated = {}
        for path in data_files(folder):
            m = CORES_RE.match(os.path.basename(path))
            if m and m.group("arch") == arch:
                dated[m.group("date")] = path
        if not dated:
            continue
        newest = max(dated)
        for date, path in dated.items():
            if date != newest:
                print("pruning cores tarball %s" % os.path.basename(path))
                os.remove(path)
                if os.path.isfile(path + ".sha256"):
                    os.remove(path + ".sha256")
        entry = file_entry(repo, base_url, dated[newest])
        entry["date"] = newest
        latest[arch] = entry
    if latest:
        write_json(os.path.join(root, "latest.json"), latest)
    return latest


#*******************************
# Raspberry Pi images
#*******************************
# the Imager repositories the page offers, as written by this run: (file name under rpi-imager/, channel pill
# class, label) - filled by write_imager_list(), read by imager_notice()
IMAGER_LISTS = []
IMAGER_CHANNELS = {"os_list.json": ("rel", "release"), "os_list-testing.json": ("pre", "testing"),
                   "os_list-nightly.json": ("dev", "nightly")}


def write_imager_list(repo, base_url, name, template, files, channel=""):
    """rpi-imager/<name>: make_rpi_image.sh's rpi_imager_repo.json for an image set (template) with the
    placeholders filled from the published files (files: arch -> file entry) - which image an entry is, by the
    download hash the template carries, else by the architecture its url placeholder or name spells. An entry
    with no image in the set is left out (a build that made one architecture only); a channel's name goes into
    the entries' names ("AutoBleem testing (32-bit)"). No template or no image: the list is removed."""
    path = os.path.join(repo, "rpi-imager", name)
    os_list = None
    if template and files and os.path.isfile(template):
        with open(template, encoding="utf-8") as f:
            os_list = json.load(f)
        icon = base_url + "/rpi-imager/icon.png"
        kept = []
        for entry in os_list.get("os_list", []):
            match = None
            for arch, file in files.items():
                if entry.get("image_download_sha256") == file["sha256"]:
                    match = file
            if match is None:
                hint = (entry.get("url", "") + " " + entry.get("name", "")).lower()
                for arch, file in files.items():
                    if arch in hint or (arch == "armhf" and "32-bit" in hint) or (arch == "arm64" and "64-bit" in hint):
                        match = file
            if match is None:
                continue
            entry["url"] = match["url"]
            entry["image_download_sha256"] = match["sha256"]
            entry["image_download_size"] = match["size"]
            if os.path.isfile(os.path.join(repo, "rpi-imager", "icon.png")):
                entry["icon"] = icon
            if channel and channel not in entry.get("name", ""):
                entry["name"] = entry.get("name", "AutoBleem").replace("AutoBleem", "AutoBleem " + channel, 1)
            kept.append(entry)
        os_list["os_list"] = kept
        if not kept:
            os_list = None
    if os_list is None:
        if os.path.isfile(path):
            os.remove(path)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, os_list)
    IMAGER_LISTS.append(name)
    return True


def index_images(repo, base_url):
    root = os.path.join(repo, "rpi-imager", "images")
    versions = {}  # version -> {arch: entry}
    if os.path.isdir(root):
        for version in os.listdir(root):
            folder = os.path.join(root, version)
            if not os.path.isdir(folder):
                continue
            note_published(folder)
            for path in data_files(folder):
                m = IMAGE_RE.match(os.path.basename(path))
                if m:
                    versions.setdefault(version, {})[m.group("arch")] = file_entry(repo, base_url, path)
    if not versions:
        return versions
    # one pre-release image set at most, the newest; Imager gets the newest stable set, else that one
    pre = [v for v in versions if is_prerelease(v)]
    stable = [v for v in versions if not is_prerelease(v)]
    if len(pre) > 1:
        keep = newest_of(pre)
        prune([os.path.join(root, v) for v in pre if v != keep], [], "pre-release image set")
        versions = {v: f for v, f in versions.items() if v == keep or v in stable}
    # one Imager repository per channel (the owner's ask, 2026-09-23): os_list.json the newest stable set - none
    # while there is no stable release (a pre-release is the testing list's, never the release one's) - and
    # os_list-testing.json the one pre-release set; os_list-nightly.json is index_nightly()'s
    pre = [v for v in versions if is_prerelease(v)]
    stable = [v for v in versions if not is_prerelease(v)]
    released = newest_of(stable)
    write_imager_list(repo, base_url, "os_list.json",
                      os.path.join(root, released, "rpi_imager_repo.json") if released else None,
                      versions.get(released))
    testing = newest_of(pre)
    write_imager_list(repo, base_url, "os_list-testing.json",
                      os.path.join(root, testing, "rpi_imager_repo.json") if testing else None,
                      versions.get(testing), "testing")
    return versions


#*******************************
# PC stick images
#*******************************
def index_pc_images(repo, base_url):
    """pc/images/<version>/autobleem-<version>-pcusb-i386.img.xz (+ .sha256; tools/make_pc_image.sh) - one
    pre-release set at most, stable ones kept; latest.json = the newest stable, else the pre-release."""
    root = os.path.join(repo, "pc", "images")
    versions = {}  # version -> {arch: entry}
    if os.path.isdir(root):
        for version in os.listdir(root):
            folder = os.path.join(root, version)
            if not os.path.isdir(folder):
                continue
            note_published(folder)
            for path in data_files(folder):
                m = PC_IMAGE_RE.match(os.path.basename(path))
                if m:
                    versions.setdefault(version, {})[m.group("arch")] = file_entry(repo, base_url, path)
    if not versions:
        return versions
    pre = [v for v in versions if is_prerelease(v)]
    stable = [v for v in versions if not is_prerelease(v)]
    if len(pre) > 1:
        keep = newest_of(pre)
        prune([os.path.join(root, v) for v in pre if v != keep], [], "pre-release PC image set")
        versions = {v: f for v, f in versions.items() if v == keep or v in stable}
    def catalog(name, version):
        path = os.path.join(root, name)
        if version:
            entry = {"version": version, "prerelease": is_prerelease(version)}
            entry.update(versions[version])
            write_json(path, entry)
        elif os.path.isfile(path):
            os.remove(path)

    # latest.json (the newest stable, else the pre-release) for what read it before the channels; release.json
    # and testing.json for the flasher's channel picker (2026-09-23) - the nightly's image is nightly/latest.json's
    catalog("latest.json", newest_of(stable) or newest_of(versions))
    catalog("release.json", newest_of(stable))
    catalog("testing.json", newest_of([v for v in versions if is_prerelease(v)]))
    return versions


#*******************************
# pcsx-abnxt, the next emulator
#*******************************
def pcsx_version_key(version):
    """pcsx-abnxt's r26-20-gb9801962 (git describe: upstream's tag, our commits past it, the commit) -> (26, 20),
    a bare r26 -> (26, 0); pcsx-ab's 20260920-fc8c992 (the date and the commit - that repository has no
    tags) -> (20260920, 0). A commit hash has no order, so two builds the key cannot tell apart (the same
    day's pcsx-ab builds) are ordered by when they were published (PUBLISHED_AT) - the first publish of
    a second same-day build kept the older one, whose hash happened to sort higher.

    Our own tags on top of upstream's, r26-alpha1 and the r26-alpha1-3-g... describes after it, sort above
    every plain r26-N-g... build: the tag was cut after them, and once it exists every later describe
    carries its label (the label, then the commits past it). Before this, r26-alpha1 keyed as (26, 0), lost
    to r26-60 and the index deleted the alpha it had just been given."""
    # the unified release tags every AutoBleem 2 repository is cut with since v2.0.0-alpha1 (v2.0.0-alpha2,
    # v2.1.0, ...): above every legacy build (a first key no date or r-number reaches), and among themselves
    # in semver order - a pre-release below its release, alpha2 below alpha10 below beta1. Before this they
    # keyed as (0, ...), lowest of all, and the index deleted the version it had just been given.
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)(\d*)(.*))?$", version)
    if m:
        pre = m.group(4)
        return (10 ** 9, (int(m.group(1)), int(m.group(2)), int(m.group(3))), 0 if pre else 1,
                (pre or "", int(m.group(5) or 0), m.group(6) or ""), PUBLISHED_AT.get(version, 0), version)
    m = re.match(r"^r(\d+)(?:-(\d+)-g[0-9a-f]+)?$", version)
    if m:
        return (int(m.group(1)), 0, "", int(m.group(2) or 0), PUBLISHED_AT.get(version, 0), version)
    m = re.match(r"^r(\d+)-([a-z]+\d*)(?:-(\d+)-g[0-9a-f]+)?$", version)
    if m:
        return (int(m.group(1)), 1, m.group(2), int(m.group(3) or 0), PUBLISHED_AT.get(version, 0), version)
    m = re.match(r"^(\d{8})-[0-9a-f]+$", version)
    if m:
        return (int(m.group(1)), 0, "", 0, PUBLISHED_AT.get(version, 0), version)
    return (0, 0, "", 0, PUBLISHED_AT.get(version, 0), version)


def index_pcsx(repo, base_url, name="pcsx-abnxt"):
    """emu/<name>/<version>/<name>-<version>-<platform>.tar.gz|zip (+ <name>-<version>.json), name = pcsx-ab or
    pcsx-abnxt - the newest version kept, the rest deleted, latest.json = the newest."""
    root = os.path.join(repo, "emu", name)
    builds = {}  # version -> {"files": {plat: entry}, "manifest": url}
    if os.path.isdir(root):
        for version in os.listdir(root):
            folder = os.path.join(root, version)
            if not os.path.isdir(folder):
                continue
            for path in data_files(folder):
                m = PCSX_RE.match(os.path.basename(path))
                if m and m.group("name") == name and m.group("version") == version:
                    builds.setdefault(version, {"files": {}})["files"][m.group("plat")] = file_entry(repo, base_url, path)
                    stamp = path + ".sha256"
                    PUBLISHED_AT[version] = max(PUBLISHED_AT.get(version, 0),
                                                os.path.getmtime(stamp if os.path.isfile(stamp) else path))
            manifest = os.path.join(folder, "%s-%s.json" % (name, version))
            if version in builds and os.path.isfile(manifest):
                builds[version]["manifest"] = base_url + "/emu/%s/%s/%s-%s.json" % (name, version, name, version)
                try:
                    with open(manifest, encoding="utf-8") as f:
                        builds[version]["note"] = json.load(f).get("note", "")
                except (OSError, ValueError):
                    pass
    if builds:
        newest = sorted(builds, key=pcsx_version_key)[-1]
        prune([os.path.join(root, v) for v in builds if v != newest], [], name + " build")
        builds = {newest: builds[newest]}
        latest = {"version": newest}
        latest.update(builds[newest])
        write_json(os.path.join(root, "latest.json"), latest)
    return builds


#*******************************
# sample games
#*******************************
def index_samples(repo, base_url):
    """samples/samples-<date>.tar.gz (+ samples-<date>.json, what is inside - tools/build_samples.py) - the
    newest kept; latest.json is what payload_linux/install.sh reads (url, sha256, date, the games)."""
    root = os.path.join(repo, "samples")
    dated = {}
    for path in data_files(root):
        m = SAMPLES_RE.match(os.path.basename(path))
        if m:
            dated[m.group("date")] = path
    if not dated:
        return None
    newest = max(dated)
    for date, path in dated.items():
        if date != newest:
            print("pruning sample pack %s" % os.path.basename(path))
            for f in (path, path + ".sha256", os.path.join(root, "samples-%s.json" % date)):
                if os.path.isfile(f):
                    os.remove(f)
    entry = file_entry(repo, base_url, dated[newest])
    entry["date"] = newest
    manifest = os.path.join(root, "samples-%s.json" % newest)
    if os.path.isfile(manifest):
        entry["manifest"] = base_url + "/samples/samples-%s.json" % newest
        try:
            with open(manifest, encoding="utf-8") as f:
                entry["games"] = json.load(f).get("games", [])
        except (OSError, ValueError):
            pass
    write_json(os.path.join(root, "latest.json"), entry)
    return entry


#*******************************
# cover databases
#*******************************
def index_db(repo, base_url):
    return [file_entry(repo, base_url, p) for p in data_files(os.path.join(repo, "db"))]


MANUAL_LANGUAGES = {"en": "English", "pl": "Polski"}
MANUAL_RE = re.compile(r"^(?P<stem>.+)-(?P<lang>[a-z]{2})\.pdf$")


def index_manuals(repo, base_url):
    """manuals/<name>-<lang>.pdf (tools/build_manuals.py) -> [(language name, file entry)], English first."""
    found = []
    for path in data_files(os.path.join(repo, "manuals")):
        m = MANUAL_RE.match(os.path.basename(path))
        if m:
            found.append((m.group("lang"), file_entry(repo, base_url, path)))
    order = list(MANUAL_LANGUAGES)
    found.sort(key=lambda x: (order.index(x[0]) if x[0] in order else len(order), x[0]))
    return [(MANUAL_LANGUAGES.get(lang, lang), f) for lang, f in found]


#*******************************
# development builds
#*******************************
# one development build on the site (the owner's call, 2026-09-23 - the build server's disk ran full); an older
# one stays only while the newest has no images yet (a run publishes its packages ~30 min before its images)
NIGHTLY_KEEP = 1


def nightly_folders_to_keep(folders, has_images):
    """The newest NIGHTLY_KEEP of `folders` (oldest first), plus the newest older one with images while none of
    those has any - so the site and Imager's nightly list are never without images between two publishes."""
    keep = folders[-NIGHTLY_KEEP:]
    if keep and not any(has_images(f) for f in keep):
        older = [f for f in folders[:-NIGHTLY_KEEP] if has_images(f)]
        if older:
            keep = [older[-1]] + keep
    return keep


def index_nightly(repo, base_url):
    """nightly/<version>/ - the development builds of develop (the nightly run, or one started by hand): the
    packages a release has, named by `git describe` (v2.0.0-alpha2-14-gabc1234), and the images when that run
    made them. The NIGHTLY_KEEP newest by publish time are kept; each folder gets release.json + SHA256SUMS,
    nightly/latest.json is the newest. An installed launcher's update check never reads this - it stays on
    releases/ (latest.json, unstable.json)."""
    root = os.path.join(repo, "nightly")
    if not os.path.isdir(root):
        return []

    def published(folder):
        # the newest sidecar in the folder is when the build went up (the folder's own mtime is not reliable)
        times = [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder) if n.endswith(".sha256")]
        return max(times) if times else os.path.getmtime(folder)

    folders = sorted((os.path.join(root, v) for v in os.listdir(root) if os.path.isdir(os.path.join(root, v))),
                     key=published)
    def has_images(folder):
        return any(IMAGE_RE.match(os.path.basename(p)) or PC_IMAGE_RE.match(os.path.basename(p))
                   for p in data_files(folder))

    keep = nightly_folders_to_keep(folders, has_images)
    prune([f for f in folders if f not in keep], [], "development build")
    builds = []
    for folder in keep:
        files, images, others = {}, {}, []
        for path in data_files(folder):
            entry = file_entry(repo, base_url, path)
            name = entry["name"]
            m = IMAGE_RE.match(name)
            pm = PC_IMAGE_RE.match(name)
            if m or pm:
                images["pc-" + pm.group("arch") if pm else m.group("arch")] = entry
                continue
            kind = next((k for k, pattern, _ in PACKAGE_KINDS if pattern.match(name)), None)
            if kind and kind not in files:
                files[kind] = entry
            else:
                others.append(entry)
        if not files and not images and not others:
            continue
        with open(os.path.join(folder, "SHA256SUMS"), "w", encoding="utf-8") as f:
            for entry in list(files.values()) + list(images.values()) + others:
                f.write("%s  %s\n" % (entry["sha256"], entry["name"]))
        build = {
            "version": os.path.basename(folder),
            "channel": "dev",
            "date": datetime.fromtimestamp(published(folder), timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "files": files,
            "images": images,
            "other_files": others,
        }
        write_json(os.path.join(folder, "release.json"), build)
        builds.append(build)
    path = os.path.join(root, "latest.json")
    if builds:
        write_json(path, builds[-1])
    elif os.path.isfile(path):
        os.remove(path)
    # the newest Pi images as Imager's third repository (the image job publishes make_rpi_image.sh's
    # rpi_imager_repo.json next to them) - from the newest build that has them, see nightly_folders_to_keep
    with_images = [b for b in builds if any(a in ("armhf", "arm64") for a in b["images"])]
    newest = with_images[-1] if with_images else None
    write_imager_list(repo, base_url, "os_list-nightly.json",
                      os.path.join(root, newest["version"], "rpi_imager_repo.json") if newest else None,
                      {a: f for a, f in (newest or {}).get("images", {}).items() if a in ("armhf", "arm64")},
                      "nightly")
    return builds


#*******************************
# the landing page
#*******************************
# Styled after the ab2 theme: its background (the logo is painted into it) as the hero, its navy/cyan
# palette, its Selawik Light font - all under /assets, staged by tools/repo_assets.py.
PAGE_CSS = """
@font-face{font-family:Selawik;src:url(/assets/selawik-light.ttf) format('truetype');font-weight:300;font-display:swap}
:root{--navy:#061a3a;--panel:rgba(4,22,56,.82);--line:rgba(80,200,255,.28);--cyan:#4fc8ff;--ink:#e8f2ff;--dim:#9fb8d6;
  --rel:#58e0a0;--pre:#ffc857;--dev:#c79bff;--warn:#ff8a65}
*{box-sizing:border-box}
html{scroll-padding-top:4rem}
body{margin:0;font-family:Selawik,"Segoe UI",system-ui,sans-serif;font-weight:300;color:var(--ink);line-height:1.5;
  background:var(--navy) radial-gradient(ellipse at 50% 0,#0b3a7a 0,#071f47 45%,#040f26 100%) fixed}
a{color:var(--cyan);text-decoration:none}a:hover{color:#fff;text-decoration:underline}
header.top{position:sticky;top:0;z-index:5;background:rgba(4,15,38,.92);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line)}
header.top .bar{max-width:68rem;margin:0 auto;padding:.55rem 1rem;display:flex;align-items:center;gap:1rem}
header.top .brand{display:flex;align-items:center;gap:.6rem;color:#fff;font-size:1.15rem;letter-spacing:.04em}
header.top .brand img{width:30px;height:30px}
header.top .brand span{color:var(--dim);font-size:.95rem}
header.top .brand:hover{text-decoration:none}
header.top nav{margin-left:auto;display:flex;gap:1.1rem;font-size:.95rem}
.hero{border-bottom:1px solid var(--line);background:linear-gradient(90deg,rgba(4,15,38,.6),rgba(11,58,122,.35))}
.hero .in{max-width:68rem;margin:0 auto;padding:0 1rem;height:clamp(96px,15vw,180px);display:flex;align-items:center;gap:1rem}
.hero p{flex:1;margin:0;font-size:clamp(1rem,2vw,1.4rem);color:#fff;max-width:34rem}
.hero img{height:100%;width:auto;margin-left:auto;display:block;
  -webkit-mask-image:linear-gradient(90deg,transparent 0,#000 18%,#000 82%,transparent 100%);
  mask-image:linear-gradient(90deg,transparent 0,#000 18%,#000 82%,transparent 100%)}
main{max-width:68rem;margin:0 auto 3rem;padding:0 1rem}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:1.1rem 1.3rem;margin:1rem 0}
.lede{color:var(--dim);margin:1rem 0 .4rem;font-size:.98rem}
.lede b{color:var(--ink);font-weight:400}
h1{font-weight:300;font-size:1.7rem;margin:0 0 .4rem;color:#fff}
h2{font-weight:300;font-size:1.2rem;letter-spacing:.04em;margin:0 0 .6rem;color:var(--cyan)}
h2 small,h1 small{font-size:.75em;color:var(--dim);letter-spacing:0;margin-left:.5rem}
h3{font-weight:400;font-size:.95rem;margin:1rem 0 .4rem;color:var(--dim)}
h3 small{font-weight:300}
p{margin:.4rem 0 .8rem}
ul,ol{padding-left:1.3rem}li{margin:.3rem 0}
ul.what{margin:.3rem 0 .9rem}ul.what b{color:var(--ink);font-weight:400}
code{font-family:ui-monospace,Consolas,monospace;font-size:.88em;color:#fff;background:rgba(255,255,255,.07);
  padding:.05em .35em;border-radius:3px}
table{border-collapse:collapse;width:100%;margin:.4rem 0 .2rem}
td,th{text-align:left;padding:.5rem .55rem;border-bottom:1px solid rgba(80,200,255,.12);vertical-align:middle}
th{font-weight:300;color:var(--dim);font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;padding-top:.2rem}
tr:last-child td{border-bottom:0}
td.what small{display:block;color:var(--dim);font-size:.83rem;line-height:1.35;margin-top:.1rem}
td.file{white-space:nowrap}
td.file a{display:inline-block;padding:.2rem .7rem;border:1px solid var(--line);border-radius:4px;
  background:rgba(79,200,255,.08);font-size:.88rem}
td.file a:hover{background:rgba(79,200,255,.22);text-decoration:none}
td.file a:before{content:"\\2193  "}
td.size{white-space:nowrap;color:var(--dim);text-align:right}
th.size{text-align:right}
td.when{white-space:nowrap;color:var(--dim);font-size:.85em}
.chan{display:inline-block;white-space:nowrap;font-size:.78rem;padding:.08rem .5rem;border-radius:999px;
  border:1px solid currentColor;color:var(--dim)}
.chan.rel{color:var(--rel)}.chan.pre{color:var(--pre)}.chan.dev{color:var(--dev)}
.badge{display:inline-block;font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;padding:.02rem .45rem;
  border-radius:3px;background:rgba(255,138,101,.16);color:var(--warn);margin-left:.4rem;vertical-align:1px}
.warn{color:var(--warn)}
a.dl{display:inline-block;padding:.25rem .7rem;border:1px solid var(--line);border-radius:4px;background:rgba(79,200,255,.08)}
a.dl:hover{background:rgba(79,200,255,.2);text-decoration:none}
.older{color:var(--dim);font-size:.9rem}
details.inputs{margin:1rem 0;border:1px dashed var(--line);border-radius:8px;background:rgba(4,22,56,.45)}
details.inputs>summary{cursor:pointer;padding:.75rem 1.3rem;color:var(--dim);list-style:none;display:flex;gap:.6rem;align-items:baseline}
details.inputs>summary::-webkit-details-marker{display:none}
details.inputs>summary:before{content:"\\25B8";color:var(--cyan);transition:transform .15s}
details.inputs[open]>summary:before{transform:rotate(90deg)}
details.inputs>summary b{color:var(--ink);font-weight:400}
details.inputs>div{padding:0 1.3rem 1rem}
h2.plat{margin:2rem 0 .2rem;padding-bottom:.3rem;border-bottom:1px solid var(--line);color:#fff;font-size:1.4rem}
nav.tabs{display:flex;flex-wrap:wrap;gap:.3rem;margin:1.2rem 0 0;border-bottom:1px solid var(--line)}
nav.tabs a{padding:.55rem 1.1rem;border:1px solid transparent;border-bottom:0;border-radius:6px 6px 0 0;
  color:var(--dim);font-size:.98rem;margin-bottom:-1px}
nav.tabs a:hover{color:#fff;text-decoration:none}
nav.tabs a.active{background:var(--panel);color:var(--cyan);border-color:var(--line)}
body.js section.tab{display:none}
body.js section.tab.active{display:block}
body.js section.tab h2.plat{display:none}
nav.subtabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:1rem 0 .4rem}
nav.subtabs a{padding:.3rem .9rem;border:1px solid var(--line);border-radius:999px;background:rgba(4,22,56,.5);
  color:var(--dim);font-size:.9rem}
nav.subtabs a:hover{color:#fff;text-decoration:none}
nav.subtabs a.active{background:var(--panel);color:var(--cyan);border-color:var(--cyan)}
h3.subtab{font-size:1.15rem;color:#fff;margin:1.4rem 0 .2rem}
body.js section.subtab{display:none}
body.js section.subtab.active{display:block}
body.js section.subtab h3.subtab{display:none}
.notice{display:flex;align-items:center;flex-wrap:wrap;gap:.5rem .8rem;margin:.8rem 0 1rem;padding:.75rem 1rem;
  border:1px solid var(--line);border-left:3px solid var(--cyan);border-radius:6px;background:rgba(79,200,255,.07)}
.notice .label{flex-basis:100%;color:var(--dim);font-size:.88rem}
.notice .label b{color:var(--ink);font-weight:400}
.notice .nrow{display:flex;align-items:center;gap:.8rem;width:100%}
.notice .nrow .chan{min-width:5.2rem;text-align:center}
.notice code{flex:1;min-width:0;overflow-wrap:anywhere;font-size:.9rem;padding:.35rem .6rem;background:rgba(0,0,0,.28)}
button.copy{font:inherit;font-size:.88rem;color:var(--cyan);background:rgba(79,200,255,.08);border:1px solid var(--line);
  border-radius:4px;padding:.3rem .9rem;cursor:pointer}
button.copy:hover{background:rgba(79,200,255,.22);color:#fff}
button.copy.done{color:var(--rel);border-color:var(--rel)}
footer{color:var(--dim);font-size:.8rem;text-align:center;margin-top:2rem}
@media (max-width:640px){
  td.when,th.when,td.size,th.size{display:none}
  .chan{white-space:normal;word-break:break-all}
  td.file a{padding:.2rem .5rem}
  .panel,details.inputs>div{padding-left:.8rem;padding-right:.8rem}
  nav.tabs a{padding:.45rem .7rem;font-size:.9rem}
  td,th{padding:.45rem .35rem}
  header.top nav{gap:.7rem;font-size:.85rem}
  header.top .brand span{display:none}
  .hero img{display:none}
}
"""


def page_head(title, tagline):
    """The top of every page: the document head, a slim bar with the emblem and the links, and a short banner -
    the page's line on the left, the ab2 theme's AutoBleem 2 picture whole on the right - so the first screen
    shows what to download, not only the picture (the old hero was 590 px tall)."""
    e = html.escape
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s</title><link rel=\"icon\" href=\"/assets/icon.png\"><style>%s</style>%s</head><body>"
            "<header class=\"top\"><div class=\"bar\"><a class=\"brand\" href=\"/\"><img src=\"/assets/icon.png\" alt=\"\">"
            "AutoBleem 2 <span>Downloads</span></a><nav>"
            "<a href=\"/#manuals\">Manual</a><a href=\"/releases/\">All files</a>"
            "<a href=\"https://github.com/autobleem2\">GitHub</a></nav></div></header>"
            "<div class=\"hero\"><div class=\"in\"><p>%s</p><img src=\"/assets/hero.jpg\" alt=\"AutoBleem 2\"></div></div>"
            % (e(title), PAGE_CSS, COPY_SCRIPT, e(tagline)))


# the Copy buttons (imager_notice): the clipboard API on the https site, a hidden textarea where it is missing
COPY_SCRIPT = """<script>
function abCopy(b){
  var t=b.dataset.copy;
  function ok(){ b.textContent='Copied'; b.classList.add('done');
    setTimeout(function(){ b.textContent='Copy'; b.classList.remove('done'); },1800); }
  function fallback(){ var a=document.createElement('textarea'); a.value=t; a.style.position='fixed'; a.style.opacity='0';
    document.body.appendChild(a); a.select(); try{ document.execCommand('copy'); ok(); }catch(e){} document.body.removeChild(a); }
  if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(t).then(ok,fallback); } else { fallback(); }
}
</script>"""


def imager_notice(base_url):
    """The Raspberry Pi Imager repository addresses in a box of their own, one row per channel (release,
    testing, nightly - the ones this run wrote), each with a button that copies it - the one thing on the page a
    user has to type into another program."""
    names = [n for n in ("os_list.json", "os_list-testing.json", "os_list-nightly.json") if n in IMAGER_LISTS]
    if not names:
        return ""
    rows = []
    for name in names:
        cls, label = IMAGER_CHANNELS[name]
        url = html.escape(base_url + "/rpi-imager/" + name)
        rows.append("<div class=\"nrow\"><span class=\"chan %s\">%s</span><code>%s</code><button type=\"button\" "
                    "class=\"copy\" data-copy=\"%s\" onclick=\"abCopy(this)\">Copy</button></div>" % (cls, label, url, url))
    return ("<div class=\"notice\"><div class=\"label\"><b>Raspberry Pi Imager repository</b> - "
            "<i>App Options &rarr; Content Repository &rarr; Use custom URL</i>, one per channel</div>%s</div>"
            % "".join(rows))


def render_index(base_url, releases, builds, cores, images, dbs, psc_builds, psc_cores, samples=None, psc_libs=None,
                 psc_apps=None, psc_bios=None, pc=None, pcsx=None, manuals=None, psc_kernel=None, nightly=None):
    """The page: a tab per platform, each leading with what a user installs from (the installer, the images,
    the packages) in one table across the three channels - the latest release, the one pre-release, the
    newest development build - and, folded away under it, the build inputs the installers, the image build and
    the CI fetch from here (RetroArch builds, cores, libraries, the kernel payload, the cover databases)."""
    e = html.escape

    def chan(text, cls=""):
        return "<span class=\"chan %s\">%s</span>" % (cls, e(text)) if text else ""

    def row(label, f, version="", cls="", note="", badge=""):
        """one file: what it is (a note under it, a badge after it), its version as a channel pill, the file,
        its size and the day it went up (the full time on hover). The file is a button named by its type, the
        whole name on hover - the names carry the version again and wrapped mid-word in a narrow column"""
        when = f.get("uploaded", "")
        m = re.search(r"\.(tar\.gz|img\.xz|zip|exe|txt|db|pdf)$", f["name"])
        return ("<tr><td class=\"what\">%s%s%s</td><td>%s</td><td class=\"file\"><a href=\"%s\" title=\"%s\">%s</a></td>"
                "<td class=\"size\">%s</td><td class=\"when\" title=\"%s\">%s</td></tr>" % (
                    e(label), "<span class=\"badge\">%s</span>" % e(badge) if badge else "",
                    "<small>%s</small>" % note if note else "", chan(version, cls),
                    e(f["url"]), e(f["name"]), e(m.group(1) if m else "file"), human(f["size"]), e(when), e(when[:10])))

    def table(rows):
        if not rows:
            return ""
        body = "".join(rows)
        if "class=\"chan" not in body:
            # nothing in it has a version (the manuals, the cover databases): no empty column
            return ("<table><thead><tr><th>What</th><th>Download</th><th class=\"size\">Size</th><th class=\"when\">Date</th>"
                    "</tr></thead><tbody>%s</tbody></table>" % body.replace("<td></td><td class=\"file\">", "<td class=\"file\">"))
        return ("<table><thead><tr><th>What</th><th>Version</th><th>Download</th><th class=\"size\">Size</th>"
                "<th class=\"when\">Date</th></tr></thead><tbody>%s</tbody></table>" % "".join(rows))

    def inputs(summary, body):
        """the build inputs, folded: a user installs from the table above, the installers and CI from these"""
        return ("<details class=\"inputs\"><summary><b>Build inputs</b> %s</summary><div>%s</div></details>"
                % (summary, body))

    stable = [r for r in releases if not r["prerelease"]]
    pre = [r for r in releases if r["prerelease"]]
    nightly = nightly or []
    channels = []  # (release dict, pill class, pill text)
    if stable:
        channels.append((stable[-1], "rel", stable[-1]["version"]))
    if pre:
        channels.append((pre[-1], "pre", pre[-1]["version"]))
    if nightly:
        channels.append((nightly[-1], "dev", "dev " + nightly[-1]["version"]))

    def release_rows(kinds, short=None):
        """the packages of these kinds in each channel - release, pre-release, development build"""
        short = short or {}
        out = []
        for which, cls, text in channels:
            for kind, _, kind_title in PACKAGE_KINDS:
                if kind in kinds and kind in which["files"]:
                    out.append(row(short.get(kind, kind_title), which["files"][kind], text, cls))
        return out

    def dev_images(titles):
        """the newest development build's images, when that run made any (index_nightly: armhf, arm64, pc-i386)"""
        if not nightly:
            return []
        dev = nightly[-1]
        return [row(title, dev["images"][key], "dev " + dev["version"], "dev")
                for key, title in titles if key in (dev.get("images") or {})]

    def older():
        if len(stable) > 1:
            return ["<p class=\"older\">Older releases: %s</p>" % ", ".join(
                "<a href=\"/releases/%s/\">%s</a>" % (e(r["version"]), e(r["version"])) for r in reversed(stable[:-1]))]
        return []

    def json_links(*pairs):
        return " &middot; ".join("<a href=\"%s\">%s</a>" % (e(u), e(t)) for u, t in pairs if u)

    out = [page_head("AutoBleem downloads",
                     "The game launcher for the PlayStation Classic, the Raspberry Pi and the PC.")]
    out.append("<main>")
    out.append("<p class=\"lede\">Pick your platform. <b>Release</b> is the tested build, <b>pre-release</b> the "
               "next one being tested, <b>dev</b> the newest development build (nightly or on request - it may "
               "not work). Every file has a <code>.sha256</code> next to it; "
               "<a href=\"/releases/latest.json\">releases/latest.json</a> is the machine-readable list.</p>")

    # ---- PlayStation Classic ----
    out.append("<h2 class=\"plat\" id=\"psc\">PlayStation Classic</h2>")
    out.append("<div class=\"panel\"><h2>Install</h2>"
               "<p>Set the console up from a Windows PC: unzip the installer, plug in a USB stick, run "
               "<code>AutoBleemInstaller.exe</code>. It prepares the stick (FAT32, named <code>SONY</code>), puts "
               "AutoBleem on it and fetches what you tick - the cover art and, if you want other systems, RetroArch "
               "with its cores, libraries, apps and BIOS files. Run it again to update: your games, saves, memory "
               "cards and settings stay.</p>")
    rows = release_rows(("installer", "psc"), {"installer": "Installer for Windows",
                                               "psc": "The stick as one zip (unzip onto a FAT32 stick named SONY)"})
    out.append(table(rows) if rows else "<p>No installer published yet.</p>")
    out += older()
    out.append("</div>")
    rows = release_rows(("psc-fs", "updateroms"), {"psc-fs": "The stick's file system (the installer's package)",
                                                   "updateroms": "UpdateRoms (the installer puts it on the stick)"})
    if psc_builds:
        newest = sorted(psc_builds, key=psc_version_key)[-1]
        rows.append(row("RetroArch for the console", psc_builds[newest]["zip"], newest,
                        note="glibc 2.24, Wayland, GLES; loads xz-compressed cores"))
    if psc_cores:
        rows.append(row("RetroArch cores", psc_cores, "",
                        note="%s cores that run on a stock console" % psc_cores.get("count", "")))
    if psc_libs:
        rows.append(row("Runtime libraries for the apps", psc_libs, "",
                        note="SDL2 image/mixer/ttf, freetype, png, vorbis and the xpad module"))
    if psc_apps:
        rows.append(row("Apps", psc_apps, "",
                        note="%s self-contained ports - Doom, OpenBOR, Amiberry, ..." % psc_apps.get("count", "")))
    if psc_bios:
        rows.append(row("BIOS list", psc_bios, "", note="%d files, %d MB - the installer fetches them from RetroBIOS; "
                        "no BIOS file is on this site" % (psc_bios["count"], psc_bios["total_bytes"] // (1024 * 1024))))
    if psc_kernel:
        rows.append(row("Kernel flasher payload", psc_kernel, "",
                        badge="preview", note="<span class=\"warn\">boot.img + abrootfs.tgz from source, not yet booted "
                        "on a console - flash only with an LBOOT.EPB backup</span>"))
    if rows:
        out.append(inputs("what the installer lays out on a stick, piece by piece",
                          table(rows) + "<p class=\"older\">Catalogs: %s</p>" % json_links(
                              ("/psc/retroarch/latest.json", "retroarch"), ("/psc/cores/latest.json", "cores"),
                              ("/psc/libs/latest.json", "libs"), ("/psc/apps/latest.json", "apps"),
                              ("/psc/bios/latest.json", "bios"), ("/psc/kernel/latest.json" if psc_kernel else "", "kernel"))))

    # ---- Raspberry Pi ----
    out.append("<h2 class=\"plat\" id=\"rpi\">Raspberry Pi</h2>")
    out.append("<div class=\"panel\"><h2>Install</h2>"
               "<p>Flash an image with <a href=\"https://www.raspberrypi.com/software/\">Raspberry Pi Imager</a> "
               "(<i>Use custom</i>) with a file from the table below, or add this site to Imager as a repository "
               "and pick AutoBleem from Imager's own list. The first boot finishes the install and needs a network. "
               "<a href=\"/rpi-install.html\">Which image for which Pi, step by step.</a></p>"
               + imager_notice(base_url))
    rpi_titles = (("armhf", "32-bit image (Pi 2/3/4/400/Zero 2) - recommended"),
                  ("arm64", "64-bit image (Pi 3/4/5/400/Zero 2)"))
    rows = []
    for version in sorted(images or {}, key=version_key, reverse=True):
        cls = "pre" if is_prerelease(version) else "rel"
        for arch, title in rpi_titles:
            f = images[version].get(arch)
            if f:
                rows.append(row(title, f, version, cls))
    rows += dev_images(rpi_titles)
    out.append(table(rows) if rows else "<p>No image published yet.</p>")
    out.append("</div>")
    rows = release_rows(("rpi", "rpi64"), {"rpi": "Package, 32-bit (install.sh)", "rpi64": "Package, 64-bit (install.sh)"})
    if builds:
        newest = newest_of(builds)
        for arch in ("armhf", "arm64"):
            if builds[newest].get(arch):
                rows.append(row("RetroArch, %s" % arch, builds[newest][arch], newest))
    for arch in ("armhf", "arm64"):
        f = (cores or {}).get(arch)
        if f:
            rows.append(row("Cores and bundles, %s" % arch, f, "",
                            note="every core buildbot has for the architecture, in one download"))
    if rows:
        out.append(inputs("the package the image installs from, and what install.sh downloads",
                          table(rows) + "<p class=\"older\">The package also installs onto a Pi already running "
                          "Raspberry Pi OS Lite: unpack it and run <code>sudo bash install.sh</code>. Catalogs: %s</p>"
                          % json_links(("/rpi/retroarch/latest.json", "retroarch"), ("/rpi/cores/latest.json", "cores"))))

    # ---- PC: two products, two sub-tabs (tabbed() splits the section on the h3.subtab headings) ----
    out.append("<h2 class=\"plat\" id=\"pc\">PC</h2>")
    pc = pc or {}
    out.append("<h3 class=\"subtab\" id=\"pc-usb\">PC USB stick</h3>")
    rows = release_rows(("flasher",), {"flasher": "Flasher for Windows"})
    how = ("on Windows with the flasher below (it downloads the image of the channel you pick), elsewhere with "
           "<code>dd</code> or balenaEtcher" if rows else "Rufus in DD mode, balenaEtcher, <code>dd</code>")
    out.append("<div class=\"panel\"><h2>Install</h2>"
               "<p>A 32-bit Debian appliance on a USB stick: write the image to a stick of 8 GB or more (%s) and "
               "boot the PC from it (BIOS or UEFI, Secure Boot off); the first boot sets AutoBleem up and the rest "
               "of the stick becomes the games partition. <a href=\"/pc-install.html\">Step by step.</a></p>" % how)
    pc_images = pc.get("images") or {}
    for version in sorted(pc_images, key=version_key, reverse=True):
        for arch, f in sorted(pc_images[version].items()):
            rows.append(row("Stick image (%s)" % arch, f, version, "pre" if is_prerelease(version) else "rel"))
    rows += dev_images((("pc-i386", "Stick image (i386)"),))
    out.append(table(rows) if rows else "<p>No stick image published yet.</p>")
    out.append("</div>")
    rows = release_rows(("pcusb",), {"pcusb": "Package (install.sh, Debian 12 i386)"})
    for tag, arches in (pc.get("builds") or {}).items():
        for arch, f in sorted(arches.items()):
            rows.append(row("RetroArch, %s" % arch, f, tag))
    for arch, f in sorted((pc.get("cores") or {}).items()):
        rows.append(row("Cores and bundles, %s" % arch, f, ""))
    if rows:
        out.append(inputs("what the stick's first boot and its updates fetch",
                          table(rows) + "<p class=\"older\">Catalogs: %s</p>" % json_links(
                              ("/pc/retroarch/latest.json", "retroarch"), ("/pc/cores/latest.json", "cores"))))

    out.append("<h3 class=\"subtab\" id=\"pc-windows\">Windows</h3>")
    out.append("<div class=\"panel\"><h2>Install</h2>"
               "<p>AutoBleem as a Windows program, per user (no administrator rights): the installer asks only for "
               "a games folder and, if you tick it, fetches RetroArch with every core. It runs full screen and "
               "keeps itself up to date (Options &rarr; Updates). Not signed: SmartScreen wants <i>More info "
               "&rarr; Run anyway</i>.</p>")
    rows = release_rows(("win-setup", "win-product", "updateroms", "win"),
                        {"win-setup": "Installer", "win-product": "Portable folder (name the games folder in dataroot.txt)",
                         "updateroms": "UpdateRoms (prepares a console stick or a Pi card on a PC)",
                         "win": "Launcher zip (a development look at a stick's tree)"})
    out.append(table(rows) if rows else "<p>Nothing published yet.</p>")
    out.append("</div>")
    win = pc.get("win") or {}
    rows = []
    if win.get("retroarch"):
        rows.append(row("RetroArch (libretro's build, repacked)", win["retroarch"], win["retroarch"]["version"]))
    if win.get("cores"):
        rows.append(row("Cores", win["cores"], ""))
    if win.get("bios"):
        rows.append(row("BIOS list", win["bios"], "", note="%d files, %d MB, fetched from RetroBIOS" % (
            win["bios"]["count"], win["bios"]["total_bytes"] // (1024 * 1024))))
    if rows:
        out.append(inputs("what the setup step fetches (libretro's servers are the fallback)", table(rows)))

    # ---- every platform ----
    if dbs or samples or pcsx or manuals:
        out.append("<h2 class=\"plat\" id=\"inputs\">Every platform</h2>")
    if manuals:
        out.append("<div class=\"panel\" id=\"manuals\"><h2>User manual</h2>"
                   "<p>Installing on every platform, the launcher and its screens, the console tools.</p>")
        out.append(table([row(lang, f) for lang, f in manuals]) + "</div>")
    emu_rows = []
    for name, heading, blurb in EMULATORS:
        builds_of = (pcsx or {}).get(name)
        if not builds_of:
            continue
        version = sorted(builds_of, key=pcsx_version_key)[-1]
        b = builds_of[version]
        cls = "pre" if is_prerelease(version) else ("rel" if version.startswith("v") else "")
        for plat, title in PCSX_PLATFORMS:
            if plat in b["files"]:
                emu_rows.append(row("%s, %s" % (name, title), b["files"][plat], version, cls))
    if emu_rows:
        out.append("<div class=\"panel\"><h2>PS1 emulators</h2><p>pcsx-abnxt (the default) and the classic pcsx-ab, "
                   "the packages every platform's installer carries; each unpacks to <code>pcsx-ab</code> + "
                   "<code>plugins/</code>. Catalogs: %s</p>" % json_links(
                       ("/emu/pcsx-abnxt/latest.json", "pcsx-abnxt"), ("/emu/pcsx-ab/latest.json", "pcsx-ab"))
                   + table(emu_rows) + "</div>")
    rows = [row("Cover art, %s" % f["name"].replace("covers", "").replace(".db", ""), f,
                note="the launcher's PS1 covers") for f in (dbs or [])]
    if samples:
        games = samples.get("games") or []
        rows.append(row("Sample games", samples, "",
                        note="%d homebrew games whose licences allow redistribution" % len(games) if games else ""))
    if rows:
        body = table(rows)
        games = (samples or {}).get("games") or []
        if games:
            names = {"psx": "PlayStation", "nes": "NES", "snes": "Super NES", "md": "Mega Drive"}
            body += ("<h3>In the sample pack</h3><table><thead><tr><th>Game</th><th>System</th><th>By</th>"
                     "<th>Licence</th></tr></thead><tbody>%s</tbody></table>" % "".join(
                         "<tr><td><a href=\"%s\">%s</a></td><td>%s</td><td>%s</td><td><a href=\"%s\">%s</a></td></tr>"
                         % (e(g.get("source", "")), e(g.get("title", "")),
                            e(names.get(g.get("system"), g.get("system", ""))), e(g.get("author", "")),
                            e(g.get("licence_url", "")), e(g.get("licence", ""))) for g in games))
        out.append(inputs("the cover databases and the sample games the installers fetch", body))

    out = tabbed(out)
    out.append("<footer>Generated %s UTC &middot; theme: ab2</footer></main></body></html>"
               % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return "\n".join(out) + "\n"


def tabbed(out):
    """The page's platform sections - everything from each <h2 class="plat" id=...> to the next - as tabs:
    a tab bar after the intro panel, one <section class="tab"> per platform, a few lines of script that
    show the one named in the URL's #hash (the first otherwise) and keep the hash in step. Without script
    every section is shown in turn, headings and all, as before."""
    html_text = "\n".join(out)
    parts = re.split(r'<h2 class="plat" id="([a-z]+)">([^<]+)</h2>', html_text)
    if len(parts) < 3:
        return out
    head, rest = parts[0], parts[1:]
    tabs = [(rest[i], rest[i + 1], rest[i + 2]) for i in range(0, len(rest), 3)]
    bar = "<nav class=\"tabs\" role=\"tablist\">" + "".join(
        "<a href=\"#%s\" data-tab=\"%s\" role=\"tab\">%s</a>" % (tid, tid, title) for tid, title, _ in tabs) + "</nav>"

    def subtabbed(parent, body):
        """a section with <h3 class="subtab" id=...> headings becomes a pill bar and one <section
        class="subtab"> per heading (the PC's two products); one without is returned as it is"""
        sub_parts = re.split(r'<h3 class="subtab" id="([a-z-]+)">([^<]+)</h3>', body)
        if len(sub_parts) < 3:
            return body
        intro, sub_rest = sub_parts[0], sub_parts[1:]
        subs = [(sub_rest[i], sub_rest[i + 1], sub_rest[i + 2]) for i in range(0, len(sub_rest), 3)]
        sub_bar = "<nav class=\"subtabs\" role=\"tablist\">" + "".join(
            "<a href=\"#%s\" data-subtab=\"%s\" data-parent=\"%s\" role=\"tab\">%s</a>" % (sid, sid, parent, title)
            for sid, title, _ in subs) + "</nav>"
        return intro + sub_bar + "".join(
            "<section class=\"subtab\" id=\"%s\" data-parent=\"%s\"><h3 class=\"subtab\">%s</h3>%s</section>"
            % (sid, parent, title, sub_body) for sid, title, sub_body in subs)

    sections = "".join(
        "<section class=\"tab\" id=\"%s\"><h2 class=\"plat\">%s</h2>%s</section>" % (tid, title, subtabbed(tid, body))
        for tid, title, body in tabs)
    script = """<script>
(function(){
  var tabs=document.querySelectorAll('nav.tabs a'), secs=document.querySelectorAll('section.tab');
  var subs=document.querySelectorAll('section.subtab'), subLinks=document.querySelectorAll('nav.subtabs a');
  if(!tabs.length) return;
  document.body.classList.add('js');
  function showSub(id){
    var parent=null;
    subs.forEach(function(s){ if(s.id===id) parent=s.dataset.parent; });
    if(!parent) return false;
    subs.forEach(function(s){ if(s.dataset.parent===parent) s.classList.toggle('active', s.id===id); });
    subLinks.forEach(function(a){ if(a.dataset.parent===parent) a.classList.toggle('active', a.dataset.subtab===id); });
    return parent;
  }
  function show(id){
    var el=id && document.getElementById(id);
    if(el && !el.matches('section.tab,section.subtab')){
      var home=el.closest('section.subtab')||el.closest('section.tab');
      if(home){ show(home.id); el.scrollIntoView(); return; }
    }
    var parent=showSub(id);
    if(parent) id=parent;
    var found=false;
    secs.forEach(function(s){ var on=(s.id===id); s.classList.toggle('active',on); if(on) found=true; });
    if(!found){ show(secs[0].id); return; }
    tabs.forEach(function(a){ a.classList.toggle('active', a.dataset.tab===id); });
    // a plain section shows its first sub-tab
    var first=null;
    subs.forEach(function(s){ if(s.dataset.parent===id && !first) first=s; });
    if(first && !parent){
      var any=false; subs.forEach(function(s){ if(s.dataset.parent===id && s.classList.contains('active')) any=true; });
      if(!any) showSub(first.id);
    }
  }
  tabs.forEach(function(a){ a.addEventListener('click', function(ev){
    ev.preventDefault(); history.replaceState(null,'','#'+a.dataset.tab); show(a.dataset.tab); }); });
  subLinks.forEach(function(a){ a.addEventListener('click', function(ev){
    ev.preventDefault(); history.replaceState(null,'','#'+a.dataset.subtab); show(a.dataset.subtab); }); });
  window.addEventListener('hashchange', function(){ show(location.hash.slice(1)); });
  show(location.hash.slice(1));
})();
</script>"""
    return [head, bar, sections, script]


#*******************************
# the Raspberry Pi manual page
#*******************************
RPI_MODELS = [
    # model, 32-bit image, 64-bit image, note
    ("Raspberry Pi 5", "yes", "yes", ""),
    ("Raspberry Pi 4 Model B", "yes", "yes", ""),
    ("Raspberry Pi 400", "yes", "yes", "the test machine - both images are tried here"),
    ("Raspberry Pi 3 Model B / B+ / A+", "yes", "yes", "1 GB of RAM (512 MB on the A+): fine for the launcher and PS1"),
    ("Raspberry Pi Zero 2 W", "yes", "yes", "512 MB of RAM; PS1 runs, the heavier RetroArch cores do not"),
    ("Raspberry Pi 2 Model B", "yes", "v1.2 only", "v1.1 has a 32-bit-only CPU; slow for anything 3D"),
    ("Compute Module 3 / 4 / 5", "yes", "yes", "with a carrier board that has HDMI and USB"),
    ("Raspberry Pi 1, Zero, Zero W", "no", "no", "ARMv6 - neither image runs on these"),
]


def render_rpi_install(base_url, images):
    e = html.escape
    newest = newest_of(images) if images else None
    out = []
    out.append(page_head("AutoBleem on a Raspberry Pi", "A PlayStation Classic-style console from a Raspberry Pi."))
    out.append("<main>")
    out.append("<div class=\"panel\"><h1>AutoBleem on a Raspberry Pi</h1>"
               "<p>AutoBleem turns a Raspberry Pi into a PlayStation Classic-style console: it boots straight into "
               "the game carousel, plays PlayStation games with its own emulator, and - with RetroArch - the "
               "other systems too. The image is Raspberry Pi OS Lite with AutoBleem's setup added; the first boot "
               "finishes the installation by itself. <a href=\"/\">&larr; Downloads</a></p></div>")

    out.append("<div class=\"panel\"><h2>Which image</h2>"
               "<p>Two images, one per flavour of Raspberry Pi OS. <strong>The 32-bit image is the one to take</strong> "
               "unless you have a reason not to: AutoBleem's PlayStation emulator has its fast ARM dynamic "
               "recompiler only on 32-bit, and every Pi from the 2 up runs it. The 64-bit image runs the "
               "same launcher with a slower (interpreted) PlayStation emulator, but RetroArch has about twice "
               "as many cores built for 64-bit ARM - pick it for the other systems on a Pi 4, 400 or 5.</p>"
               "<table><tr><th>Model</th><th>32-bit image</th><th>64-bit image</th><th>Notes</th></tr>")
    for model, b32, b64, note in RPI_MODELS:
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(model), e(b32), e(b64), e(note)))
    out.append("</table>")
    if newest:
        out.append("<p style=\"margin-top:1rem\">")
        for arch, title in (("armhf", "32-bit image"), ("arm64", "64-bit image")):
            f = images[newest].get(arch)
            if f:
                out.append("<a class=\"dl\" href=\"%s\">%s (%s)</a> " % (e(f["url"]), title, human(f["size"])))
        out.append("</p>")
    out.append("</div>")

    out.append("<div class=\"panel\"><h2>You need</h2><ul>"
               "<li>A Raspberry Pi from the table, its power supply, and an HDMI screen.</li>"
               "<li>A microSD card of <strong>16 GB or more</strong> - 32 GB and up if you want room for games "
               "(the system takes 8 GB, the rest becomes the games partition).</li>"
               "<li>A USB or Bluetooth gamepad - a DualShock 4, an Xbox pad, an 8BitDo, any pad the Pi sees as a game "
               "controller. The launcher is driven with the pad; a keyboard is only for the first boot.</li>"
               "<li><strong>Internet on the first boot</strong> (Ethernet or WiFi): the setup downloads RetroArch, "
               "its cores and the BIOS files, about a gigabyte in all.</li>"
               "<li><a href=\"https://www.raspberrypi.com/software/\">Raspberry Pi Imager</a> on a PC or Mac.</li>"
               "</ul></div>")

    out.append("<div class=\"panel\"><h2>Flashing the card</h2><ol>"
               "<li>In Imager, choose your Raspberry Pi model, then under <em>Operating System</em> pick "
               "<em>Use custom</em> and the downloaded <code>.img.xz</code> - or first add this site under "
               "<em>App Options &rarr; Content Repository</em> (the address below) and pick "
               "AutoBleem from the list.%s</li>"
               "<li>Choose the card under <em>Storage</em>.</li>"
               "<li>Say <strong>yes to customisation</strong> when Imager offers it: set a user name and password, "
               "your <strong>WiFi</strong> network and country, and enable <strong>SSH</strong>. With these preset the "
               "first boot needs no keyboard at all. (Skipping is fine too - the first boot then asks for the WiFi "
               "on the screen.)</li>"
               "<li>Write, then put the card in the Pi and power it on.</li></ol></div>" % imager_notice(base_url))

    out.append("<div class=\"panel\"><h2>The first boot</h2>"
               "<p>Raspberry Pi OS starts once to apply your presets, then AutoBleem's setup takes the screen:</p><ol>"
               "<li>It waits for the network. Without one it lists the WiFi networks it can see and asks for the "
               "password (or press <code>e</code> after plugging in an Ethernet cable).</li>"
               "<li>It asks whether to install <strong>RetroArch</strong>. <code>Y</code> (or a minute of silence) gives "
               "the full install with about 130 systems; <code>n</code> a lean PlayStation-only AutoBleem. RetroArch "
               "can be added later by running the installer again.</li>"
               "<li>It grows the system partition, creates the <code>AUTOBLEEM</code> games partition on the rest of "
               "the card, downloads RetroArch (ready-built from this site - or, when the site cannot be reached, "
               "builds it, which takes 10-40 minutes), its cores and the BIOS files, and reboots. Everything is "
               "shown on the screen; nothing needs pressing.</li>"
               "<li>The Pi comes up in the game carousel. It is empty until you add games.</li></ol>"
               "<p>If something fails (no network, a download that would not finish), the setup says so, gives the "
               "login prompt back and simply tries again on the next boot.</p></div>")

    out.append("<div class=\"panel\"><h2>Adding games</h2>"
               "<p>The <code>AUTOBLEEM</code> partition is exFAT, so any PC or Mac reads it: put the card in a reader, "
               "or copy over the network with SFTP (WinSCP, FileZilla, <code>scp</code>) to "
               "<code>/media/autobleem/</code> on the Pi once SSH is enabled.</p><ul>"
               "<li><strong>PlayStation games</strong>: drop the game files - <code>.cue</code> + <code>.bin</code>, "
               "<code>.chd</code> or <code>.pbp</code> - straight into <code>Games/</code>; the launcher sorts each game "
               "into its own folder by itself. A multi-disc game is one folder with every disc in it (make that "
               "folder yourself, or name the discs <em>Game (Disc 1)</em>, <em>Game (Disc 2)</em> and the launcher merges "
               "them). Cover art and the title come on their own (the launcher looks the game up and fetches its "
               "cover online); your own <code>&lt;name&gt;.png</code> next to the game wins.</li>"
               "<li><strong>Other systems</strong> (with RetroArch): into <code>RetroArch/roms/&lt;system&gt;/</code> - a "
               "folder per system is already there, named as RetroArch names them ("
               "<em>Nintendo - Nintendo Entertainment System</em>, <em>Sega - Mega Drive - Genesis</em>, ...).</li>"
               "<li><strong>BIOS files</strong>: the setup installs the PlayStation BIOS and RetroArch's system files; "
               "your own go to <code>System/Bios/</code> and <code>RetroArch/system/</code>.</li></ul>"
               "<p>The launcher watches its folders: copy a game in while it runs and it appears in the carousel by "
               "itself, sorted into its folder, cover and all.</p></div>")

    out.append("<div class=\"panel\"><h2>Options and updates</h2>"
               "<p><code>autobleem.txt</code> on the card's small boot partition (readable on any PC) holds the "
               "first-boot options as <code>key=value</code>: the system partition's size, the HDMI mode, the "
               "RetroArch answer, whether to mirror the box art. Edit it before the first boot; comments in the file "
               "explain each key.</p>"
               "<p>To update an installed Pi, download the Raspberry Pi tarball from the <a href=\"/\">downloads</a> "
               "page, unpack it on the Pi and run <code>sudo bash install.sh</code> - it keeps the games partition "
               "and everything on it, and skips what is already installed.</p>"
               "<p>Questions and bug reports: <a href=\"https://github.com/autobleem/AutoBleem2\">github.com/autobleem/AutoBleem2</a>. "
               "The Pi's logs are in <code>System/Logs/</code> on the games partition.</p></div>")

    out.append("<footer>Generated %s UTC &middot; theme: ab2</footer></main></body></html>"
               % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return "\n".join(out) + "\n"

#*******************************
# pc-install.html
#*******************************
def render_pc_install(base_url, images):
    """The PC stick's manual: what it is, what it runs on, writing the image, the first boot, where games go."""
    e = html.escape
    newest = newest_of(images) if images else None
    out = []
    out.append(page_head("AutoBleem on a PC USB stick", "A PlayStation Classic-style console on a USB stick for a PC."))
    out.append("<main>")
    out.append("<div class=\"panel\"><h1>AutoBleem on a PC USB stick</h1>"
               "<p>AutoBleem on a USB stick that turns any PC into a PlayStation Classic-style console: boot the PC "
               "from the stick and it comes up in the game carousel, with nothing of the PC's own disks touched. "
               "Games live on the stick itself, on a partition any computer can write to. A 32-bit Linux is inside, "
               "so an old PC works as well as a new one. <a href=\"/\">&larr; Downloads</a></p>")
    if newest:
        f = images[newest].get("i386")
        if f:
            out.append("<p><a class=\"dl\" href=\"%s\">%s (%s)</a>%s</p>" % (
                e(f["url"]), e(f["name"]), human(f["size"]),
                " - a development build" if is_prerelease(newest) else ""))
    out.append("</div>")

    out.append("<div class=\"panel\"><h2>You need</h2><ul>"
               "<li>A PC with an <strong>Intel or AMD processor</strong> - anything from a Pentium M / Athlon XP "
               "up, 32- or 64-bit; 1 GB of memory or more. The stick carries three Linux kernels and boots the one "
               "the processor calls for, from a plain BIOS or from UEFI (32- or 64-bit).</li>"
               "<li>A USB stick of <strong>8 GB or more</strong> - 32 GB and up for room for games (the system "
               "takes 8 GB, the rest becomes the games partition).</li>"
               "<li>A USB or Bluetooth gamepad - a DualShock 4, an Xbox pad, an 8BitDo, any pad Linux sees as a "
               "game controller. The launcher is driven with the pad; a keyboard is only for the first boot.</li>"
               "<li><strong>Internet on the first boot</strong> (a network cable, or WiFi - the setup asks): it "
               "downloads RetroArch, its cores, the BIOS files and the cover databases.</li>"
               "<li>A screen on HDMI or DisplayPort; the sound goes out the same cable.</li></ul>"
               "<p><strong>Graphics:</strong> Intel and AMD graphics work out of the box. Nvidia cards run on the "
               "open driver, which handles most of them; a very new one may show nothing - use another card or "
               "the processor's own graphics.</p></div>")

    out.append("<div class=\"panel\"><h2>Writing the stick</h2><ol>"
               "<li><strong>Windows:</strong> the <strong>AutoBleem Flasher</strong> (on the download page, next "
               "to the image): unzip it and run <code>AutoBleemFlasher.exe</code> - it asks for administrator "
               "rights, since it writes a whole disk. Pick the channel (Release, Testing or Nightly) and the stick; "
               "it downloads that channel's image, checks it, writes it and reads it back. Only removable disks are "
               "offered, and everything on the chosen one is erased. <a href=\"https://rufus.ie/\">Rufus</a> (in "
               "<em>DD Image mode</em>) and <a href=\"https://etcher.balena.io/\">balenaEtcher</a> work as well, "
               "with an image you downloaded yourself.</li>"
               "<li><strong>Linux / macOS:</strong> download the image (a <code>.img.xz</code> file), then "
               "<code>xzcat autobleem-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress</code> (the stick's "
               "device, not a partition of it - everything on the stick is erased).</li></ol></div>")

    out.append("<div class=\"panel\"><h2>Booting from it</h2>"
               "<p>Plug the stick in and start the PC from it: the boot menu key at power-on (F12, F11, F8 or Esc "
               "depending on the make - the PC's own screen says which), or the boot order in the BIOS/UEFI "
               "setup. <strong>Secure Boot must be off</strong> in the UEFI setup: nothing on the stick is "
               "signed. Both a BIOS (\"legacy\" / CSM) boot and a UEFI boot work.</p></div>")

    out.append("<div class=\"panel\"><h2>What the first boot does</h2>"
               "<p>The first boot is the installation, on the screen, watched and answered with the keyboard:</p><ol>"
               "<li>It asks whether to show the setup <strong>graphically</strong> (recommended, the AutoBleem "
               "logo with the questions and progress bars under it) or as <strong>text</strong> on the console - "
               "choose text if the graphical screen stays black on your PC; the choice is kept for the updates that "
               "follow.</li>"
               "<li>With no network cable it asks for a WiFi network and its password.</li>"
               "<li>It asks whether to install <strong>RetroArch</strong> (the other systems - NES, SNES, Mega "
               "Drive, arcade and about a hundred more; close to a GB of downloads). A minute with no answer "
               "means yes. Without it AutoBleem is a PlayStation-only machine.</li>"
               "<li>The system partition is grown to 8 GB and <strong>the rest of the stick becomes the "
               "<code>AUTOBLEEM</code> games partition</strong> (exFAT).</li>"
               "<li>RetroArch, its cores, the BIOS files, the cover databases and the sample games are "
               "downloaded; the boot logo is set up.</li>"
               "<li>The PC reboots into the launcher.</li></ol>"
               "<p>Something failed? The screen says so and the same boot runs again next time. The log is "
               "<code>/var/log/autobleem-firstboot-install.log</code> on the stick's Linux partition.</p></div>")

    out.append("<div class=\"panel\"><h2>Games</h2>"
               "<p>Plug the stick into any computer: the <code>AUTOBLEEM</code> drive is the games partition. "
               "PlayStation games go into <code>Games/</code>, a folder per game (<code>.cue</code>+<code>.bin</code>, "
               "<code>.pbp</code>, <code>.chd</code>) - or drop the files straight into <code>Games/</code> and the "
               "launcher sorts them into folders. The other systems' games go into <code>RetroArch/roms/</code>, a "
               "folder per system, named as they are already there. The launcher scans on every start and while "
               "it runs; covers and titles come from the databases and, when online, from libretro's thumbnails.</p>"
               "<p>Your own PlayStation BIOS (<code>romw.bin</code>, <code>romJP.bin</code>) goes into "
               "<code>System/Bios/</code>; the setup put the standard ones there already.</p></div>")

    out.append("<div class=\"panel\"><h2>Options and updates</h2>"
               "<p><code>autobleem.txt</code> on the stick's small first partition holds the first boot's "
               "options (the system partition's size, RetroArch yes/no, what to download) - edit it on any "
               "computer before the first boot; the comments in it explain each key.</p>"
               "<p>The launcher checks this site for updates once a day (<em>Options &rarr; Updates</em>, "
               "and <em>Software Update</em> in the L2+R2 menu) and installs one from inside, the games "
               "untouched.</p>"
               "<p>For a terminal: <strong>ssh</strong> is on from the first boot, user <code>autobleem</code>, "
               "password <code>autobleem</code> - change it (<code>passwd</code>). On the PC itself, Alt+F2 "
               "gives a login prompt next to the launcher.</p></div>")
    out.append("</main></body></html>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="the repository directory")
    ap.add_argument("--base-url", default=os.environ.get("AB_REPO_URL", "https://autobleem.retromenele.pl"),
                    help="what the urls in the json files start with (default: $AB_REPO_URL or the server's address)")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        sys.exit("not a directory: %s" % repo)
    base_url = args.base_url.rstrip("/")

    releases = index_releases(repo, base_url)
    builds = index_retroarch(repo, base_url)
    cores = index_cores(repo, base_url)
    pc_builds = index_retroarch(repo, base_url, "pc")
    pc_cores = index_cores(repo, base_url, "pc")
    pc_images = index_pc_images(repo, base_url)
    psc_builds = index_psc_retroarch(repo, base_url)
    psc_cores = index_psc_cores(repo, base_url)
    psc_libs = index_psc_libs(repo, base_url)
    psc_apps = index_psc_apps(repo, base_url)
    psc_bios = index_psc_bios(repo, base_url)
    psc_kernel = index_psc_kernel(repo, base_url)
    win = index_win(repo, base_url)
    images = index_images(repo, base_url)
    dbs = index_db(repo, base_url)
    samples = index_samples(repo, base_url)
    manuals = index_manuals(repo, base_url)
    nightly = index_nightly(repo, base_url)
    pcsx = {name: index_pcsx(repo, base_url, name) for name, _, _ in EMULATORS}
    pcsx = {name: b for name, b in pcsx.items() if b}
    pc = {"builds": pc_builds, "cores": pc_cores, "images": pc_images, "win": win}
    for name, page in (("index.html", render_index(base_url, releases, builds, cores, images, dbs, psc_builds, psc_cores, samples, psc_libs, psc_apps, psc_bios, pc, pcsx, manuals, psc_kernel,
                                                       nightly)),
                       ("rpi-install.html", render_rpi_install(base_url, images)),
                       ("pc-install.html", render_pc_install(base_url, pc_images))):
        tmp = os.path.join(repo, ".%s.tmp" % name)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(tmp, os.path.join(repo, name))
    print("%s: %d releases, %d RetroArch builds, %d cores tarballs, %d PSC RetroArch builds, %s PSC cores, %d image sets, "
          "%d PC RetroArch builds, %d PC cores tarballs, %d PC image sets, %d databases, %s sample pack, %d manuals" % (
        repo, len(releases), len(builds), len(cores), len(psc_builds), "1" if psc_cores else "0", len(images),
        len(pc_builds), len(pc_cores), len(pc_images), len(dbs), "1" if samples else "0", len(manuals)))


if __name__ == "__main__":
    main()
