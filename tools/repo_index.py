#!/usr/bin/env python3
"""Regenerate the machine-readable files and the landing page of the download repository.

Run on the server over the repository directory after every publish (tools/repo_publish.sh does it):

    repo_index.py /home/claude/autobleem-repo --base-url https://autobleem.retromenele.pl

Reads what is there (CLAUDE.md, "The download repository", has the layout) and writes:

    releases/<tag>/release.json        the packages of that release: name, size, sha256, url
    releases/latest.json               the newest stable release's release.json
    releases/unstable.json             the one pre-release kept, same shape
    channels.json                      the release channels the PC installers list (id, label, index, images, unstable)
    rpi/retroarch/latest.json          the newest RetroArch build per architecture
    psc/retroarch/latest.json          the newest RetroArch build for the PlayStation Classic (psc/retroarch/<tag>/)
    psc/cores/latest.json              the newest cores tarball for the console (psc/cores/cores-psc-<date>.tar.gz)
    psc/libs/latest.json               the newest runtime-library pack for the console's apps (psc/libs/libs-psc-<date>.tar.gz)
    psc/apps/latest.json               the newest pack of the console's third-party Apps (psc/apps/apps-psc-<date>.tar.gz)
    store/<platform>/catalog.json      the AutoBleem Store's catalog for a platform (psc, rpi, rpi64, pcusb, win): every
                                       <id>.item.json there, its files' sizes, sums and urls filled in
    psc/bios/latest.json               the console's BIOS list (psc/bios/biospack.txt: what the installer fetches from
                                       RetroBIOS into RetroArch/bios - only the list is here, never a BIOS file)
    win/retroarch/<v>/                 RetroArch for the Windows product: libretro's own x86_64 build repacked as
                                       retroarch-win64-<v>.tar.gz (ci/build_retroarch.sh win64), the newest kept,
                                       latest.json = the file plus "version"
    win/cores/                         cores-win64-<date>.tar.gz (ci/build_cores.sh win64), the newest kept
    win/bios/                          biospack-win64.txt, the Windows list (tools/biospack.py --arch win64)
    rpi/cores/latest.json              the newest cores tarball per architecture (rpi/cores/<arch>/)
    samples/latest.json                the newest sample-games pack (samples/samples-<date>.tar.gz, tools/build_samples.py)
    emu/pcsx-ab/latest.json            the newest build per channel of each emulator (release/testing from a v* tag
    emu/pcsx-abnxt/latest.json         in emu/<name>/<version>/, nightly from a develop push in emu/<name>/nightly/
                                       <version>/), one package per platform - each repository's tools/make_packages.sh,
                                       the classic pcsx-ab and the next one
    rpi-imager/os_list.json            the newest images' Imager metadata with real urls (from the
                                       rpi_imager_repo.json make_rpi_image.sh wrote next to them)
    index.html                         the splash page ("AutoBleem 2 is coming", SPLASH_STATUS, the Ko-fi button)
    repository/index.html              the download listing (was the landing page)
    repository/rpi-install.html        the Raspberry Pi manual: which image for which Pi, the setup, games
    repository/pc-install.html         the PC USB stick's manual: what it runs on, writing the stick, the setup
    rpi-install.html, pc-install.html  stubs that send an old link on to repository/
    store/index.html                   what the AutoBleem Store offers
    testplans/index.json               the volunteer test plans (testplans/<version>/<platform>.yaml, published from the hub):
                                       the current version and its platforms - the contract is intake/README.md
    testing/*.html                     the volunteer tester pages made from them: index, one task page per platform,
                                       report, thanks, status (none without testplans/)

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
INDEX_VERSION = 50

# the splash page's "Where we are" block updates itself (2026-10-03, the owner): the release rows come from
# index_releases (splash_release_rows: the newest stable release, the newer pre-release, the next milestone) and
# the nightly row from index_nightly's newest build. SPLASH_STATUS is for extra rows by hand, shown after the
# release rows: (label, small note, pill class, pill text); an empty pill class = not reached yet (amber ring).
SPLASH_STATUS = []
# the page icon: /assets/icon.png is cached for a day under one URL, so the link carries the icon's content hash
# (the first 8 hex digits of its sha1 - tests/test_site_pages.py checks it against tools/site-assets/icon.png;
# change both when the icon changes); /favicon.ico is what a browser asks for by itself (publish copies it there)
ICON_REV = "a3f185d9"
ICON_LINKS = ('<link rel="icon" href="/assets/icon.png?v=%s" type="image/png"><link rel="shortcut icon" '
              'href="/favicon.ico?v=%s">' % (ICON_REV, ICON_REV))
# the owner's Ko-fi page: the splash's Support button links it; empty = no button
KOFI_URL = "https://ko-fi.com/autobleem"

# the release packages, by the name they carry (tools/make_*_package.sh, ci/build.sh)
PACKAGE_KINDS = [
    ("installer", re.compile(r"^AutoBleemInstaller-.*\.zip$"),
     "PlayStation Classic installer for Windows (downloads the stick's file system from the channel picked in it)"),
    # the stick as two zips (PLATFORM-21): -base without RetroArch, -full with RetroArch and its cores; neither has a
    # BIOS file. Before "psc" - the first kind a name matches is its kind
    ("psc-base", re.compile(r"^autobleem-psc-.*-base\.zip$"),
     "PlayStation Classic, the stick as a zip without RetroArch (smaller; no BIOS files)"),
    ("psc-full", re.compile(r"^autobleem-psc-.*-full\.zip$"),
     "PlayStation Classic, the stick as a zip with RetroArch and its cores (no BIOS files)"),
    ("psc", re.compile(r"^autobleem-psc-(?!.*-(base|full)\.zip$).*\.zip$"), "PlayStation Classic (USB stick zip)"),
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
# an extension's packages under extensions/<name>/<version>/ (its repository's ci/build.sh): the extension for
# each platform, ext_<name>-<platform>-<version>.zip, and whatever programs come with it - the Store's LAN
# server, abstored-<os>-<arch>-<version>.tar.gz|zip
EXTENSION_RE = re.compile(r"^(?P<pkg>ext_[a-z0-9_]+|abstored|lanshare)-(?P<plat>psc|rpi|rpi64|pcusb|win|linux-x86_64|linux-i386|"
                          r"linux-armhf|linux-arm64|windows-x86_64)-(?P<version>.+)\.(zip|tar\.gz)$")
ABSTORED_PLATFORMS = (("linux-x86_64", "Linux PC, 64-bit"), ("linux-i386", "Linux PC, 32-bit"),
                      ("linux-arm64", "Linux ARM, 64-bit"), ("linux-armhf", "Linux ARM, 32-bit"),
                      ("windows-x86_64", "Windows"))
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
        return (0, 0, 0, 0, (0, 0, 0, tag), PUBLISHED_AT.get(tag, 0))
    major, minor, patch, suffix = m.groups()
    label = re.sub(r"-[0-9a-f]{7,40}$", "", suffix or "")
    ranks = {"pre": 0, "alpha": 1, "beta": 2, "rc": 3}
    lm = re.match(r"^(pre|alpha|beta|rc)(\d*)(?:\.(\d+))?$", label)  # alpha1.1: a point release of alpha1
    label_key = (ranks[lm.group(1)], int(lm.group(2) or 0), int(lm.group(3) or 0), "") if lm else (4, 0, 0, label)
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
    return re.search(r"-%s(-(base|full))?(-[0-9a-f]{7,40})?\.(zip|tar\.gz|exe|img\.xz)$" % re.escape(version),
                     name) is not None


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
            write_json(path, unstable_view(which[-1]) if name == "unstable.json" else which[-1])
        elif os.path.isfile(path):
            os.remove(path)
    return stable + pre


# R1-safety.md #3: a psc console on the testing channel cannot be offered a pre-release through
# unstable.json - the console's update_service.cpp stops at the first list that PARSES, whichever
# channel it is (it does not check the list actually has a psc file), so a psc pre-release named
# in unstable.json that a console then can't apply - or a bad one it can - has no second list to
# fall back to and would offer the same "update" forever. Fix is deliberately data-only, not code
# in the console: unstable.json simply never carries a "psc" file - a psc tester goes through the
# nightly channel instead (channelFiles("nightly") tries nightly/latest.json first). release.json,
# the "releases" list the download page and the installer's channelRelease/channelLists build their
# rows from, and the pre-release folder's own files are untouched - the page still lists the
# pre-release's psc zip as a manual download, and InstallerJob::channelRelease already skips a list
# with no "psc-fs" entry to try the next one, so both already show the nightly release for psc once
# a pre-release carries none (verified by reading, not by a code change there).
UNSTABLE_EXCLUDED_KINDS = ("psc", "psc-base", "psc-full")


def unstable_view(release):
    """`release`, minus the file kinds unstable.json must never carry (see UNSTABLE_EXCLUDED_KINDS) -
    a shallow copy: the caller's `release` dict (and the "files" dict written into release.json /
    returned to render_index) is never mutated."""
    if not any(kind in release["files"] for kind in UNSTABLE_EXCLUDED_KINDS):
        return release
    view = dict(release)
    view["files"] = {k: v for k, v in release["files"].items() if k not in UNSTABLE_EXCLUDED_KINDS}
    return view


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


# the corresponding-source archive a GPL item keeps on the site (source/<id>/): never one of an item's files
SOURCE_ARCHIVE_RE = re.compile(r"-source\.tar\.(gz|xz|bz2)$", re.IGNORECASE)


# The package types a Store descriptor's "category" may name (the launcher's App categories) and how the page shows them.
STORE_CATEGORIES = {"games": "Games", "emulators": "Emulators", "tools": "Tools", "media": "Media", "other": "Other",
                    "packages": "Game data"}
# a content kind (packages spec, 8.1): lower case, digits, single dashes - what `uses` and `provides` list
CONTENT_KIND_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def content_kinds(value):
    """`uses` / `provides` of a descriptor: a list of content kinds, lower-cased and trimmed; anything that is not a
    kind is dropped, and so is an empty or repeated one."""
    out = []
    for k in value if isinstance(value, list) else []:
        k = k.strip().lower() if isinstance(k, str) else ""
        if CONTENT_KIND_RE.match(k) and k not in out:
            out.append(k)
    return out


def index_store(repo, base_url, pages=None):
    """store/<platform>/: the AutoBleem Store's catalog (the launcher's docs/store-plan.md), one per platform.

    Each item is an <id>.item.json descriptor next to its files:
        {"id": "app/opentyrian", "kind": "app", "title": "OpenTyrian", "version": "2.1", "author": "...",
         "licence": "GPL-2.0", "description": "...", "serial": "...", "image": "opentyrian.png",
         "files": [{"name": "opentyrian-psc-2.1.zip", "disc": 1}], "requires": ["pack/psc-libs"]}
    and catalog.json lists them with each file's size, sha256 and url (the Store refuses a download that does
    not match). A descriptor that names a file which is not there, or lacks an id, a kind or a title, is left
    out and said so. A file no descriptor names any more (an App's previous version) is pruned.

    "category" is the package's type - games, emulators, tools, media, other or packages (game data) (any case; the
    launcher files an installed App there, the Store shows it as "Type"). Anything else, or none, is left out of the
    catalog. "uses" (the content kinds an engine runs) and "provides" (the kinds a game-data package holds) are lists
    of content kinds, passed through lower-cased; "requires" (ids of the items to install first) likewise.

    kind "package" is a game-data package (a zip with a package.ini; the Store puts it in Packages/).

    kind "pe" is a PE App (the Store's "PE Apps" tab): files is the one .mod, which the Store puts in Mods/. Its
    descriptor also carries "source_url", the address of the corresponding source archive (GPL items; shown in the
    item's details, an http(s) address, passed through to catalog.json). The source archive itself is never one of
    the files (it would land on the stick): a descriptor naming a "*-source.tar.gz" among its files is left out.

    pages, when given, gets each platform's items as the Store's page shows them (render_store): the catalog's
    fields plus each file's upload time."""
    counts = {}
    root = os.path.join(repo, "store")
    if not os.path.isdir(root):
        return counts
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for platform in sorted(os.listdir(root)):
        folder = os.path.join(root, platform)
        if not os.path.isdir(folder):
            continue
        items, named, uploaded = [], set(), {}
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".item.json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError) as e:
                print("store/%s/%s: not read (%s)" % (platform, name, e))
                continue
            if not all(d.get(k) for k in ("id", "kind", "title")):
                print("store/%s/%s: no id, kind or title - left out" % (platform, name))
                continue
            files, missing = [], []
            source_files = [f.get("name") for f in d.get("files") or [] if SOURCE_ARCHIVE_RE.search(f.get("name") or "")]
            if source_files:
                print("store/%s/%s: %s is a source archive, not a file of the item - left out" % (
                    platform, name, source_files[0]))
                continue
            for f in d.get("files") or []:
                path = os.path.join(folder, f.get("name") or "")
                if not f.get("name") or not os.path.isfile(path):
                    missing.append(f.get("name") or "(no name)")
                    continue
                entry = file_entry(repo, base_url, path)
                one = {k: entry[k] for k in ("name", "size", "sha256", "url")}
                if f.get("disc"):
                    one["disc"] = f["disc"]
                files.append(one)
                uploaded[f["name"]] = entry["uploaded"]
            if missing or not files:
                print("store/%s/%s: %s - left out" % (platform, name, "missing " + ", ".join(missing) if missing
                                                        else "no files"))
                continue
            item = {k: d[k] for k in ("id", "kind", "title", "version", "author", "licence", "description",
                                      "serial", "requires") if d.get(k)}
            category = d.get("category")
            if isinstance(category, str) and category.strip().lower() in STORE_CATEGORIES:
                item["category"] = category.strip().lower()
            for key in ("uses", "provides"):
                kinds = content_kinds(d.get(key))
                if kinds:
                    item[key] = kinds
            source_url = d.get("source_url")
            if isinstance(source_url, str) and source_url.startswith(("http://", "https://")):
                item["source_url"] = source_url
            image = d.get("image")
            if image and os.path.isfile(os.path.join(folder, image)):
                item["image"] = base_url + "/store/%s/%s" % (platform, image)
                named.add(image)
            item["files"] = files
            items.append(item)
            named.update(f["name"] for f in files)
        # what nothing names any more goes, with its sidecar
        for path in data_files(folder):
            if os.path.basename(path) not in named:
                print("pruning store/%s/%s" % (platform, os.path.basename(path)))
                for p in (path, path + ".sha256"):
                    if os.path.isfile(p):
                        os.remove(p)
        write_json(os.path.join(folder, "catalog.json"),
                   {"schema": 1, "platform": platform, "date": today, "items": items})
        counts[platform] = len(items)
        if pages is not None:
            pages[platform] = [dict(i, files=[dict(f, uploaded=uploaded.get(f["name"], "")) for f in i["files"]])
                               for i in items]
    return counts


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
                   "os_list-nightly.json": ("dev", "nightly"), "os_list-preview.json": ("dev", "preview")}


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
    # no early return on an empty tree: a full withdraw (the last image set's folder removed) must still
    # clear os_list.json/os_list-testing.json - write_imager_list(None, None) below does that itself
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
    # no early return on an empty tree: a full withdraw (the last image set's folder removed) must still
    # clear latest.json/release.json/testing.json - catalog(name, None) below does that itself
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
    # a point release (v2.0.0-alpha1.1) sits between its number and the next: alpha1 < alpha1.1 < alpha2
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)(\d*)(?:\.(\d+))?(.*))?$", version)
    if m:
        pre = m.group(4)
        return (10 ** 9, (int(m.group(1)), int(m.group(2)), int(m.group(3))), 0 if pre else 1,
                (pre or "", int(m.group(5) or 0), int(m.group(6) or 0), m.group(7) or ""),
                PUBLISHED_AT.get(version, 0), version)
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


def pcsx_channel_of(version):
    """release/testing for a v* tag build (plain vs pre-release), nightly for anything else - the
    date-and-commit or git-describe versions a develop push has always carried (pcsx-ab has no tags on
    develop at all; pcsx-abnxt's r26-N-g... describes the same way) - whether they sit in the channel's own
    emu/<name>/nightly/<version>/ (the workflow's develop-push publish) or, from before that publish existed,
    directly under emu/<name>/<version>/ (a manual `repo_publish.sh pcsx <dated-version> ...` run)."""
    if version.startswith("v"):
        return "testing" if is_prerelease(version) else "release"
    return "nightly"


def _read_pcsx_builds(repo, base_url, name, folder_root):
    """The valid <name>-<version>-<platform> builds directly under `folder_root` (a dict version -> build)."""
    builds = {}
    if not os.path.isdir(folder_root):
        return builds
    for version in os.listdir(folder_root):
        folder = os.path.join(folder_root, version)
        if not os.path.isdir(folder):
            continue
        files = {}
        for path in data_files(folder):
            m = PCSX_RE.match(os.path.basename(path))
            if m and m.group("name") == name and m.group("version") == version:
                files[m.group("plat")] = file_entry(repo, base_url, path)
                stamp = path + ".sha256"
                PUBLISHED_AT[version] = max(PUBLISHED_AT.get(version, 0),
                                            os.path.getmtime(stamp if os.path.isfile(stamp) else path))
        if not files:
            continue
        build = {"version": version, "files": files}
        manifest = os.path.join(folder, "%s-%s.json" % (name, version))
        if os.path.isfile(manifest):
            build["manifest"] = base_url + "/" + os.path.relpath(manifest, repo).replace(os.sep, "/")
            try:
                with open(manifest, encoding="utf-8") as f:
                    build["note"] = json.load(f).get("note", "")
            except (OSError, ValueError):
                pass
        builds[version] = build
    return builds


def index_pcsx(repo, base_url, name="pcsx-abnxt"):
    """emu/<name>/<version>/<name>-<version>-<platform>.tar.gz|zip (+ <name>-<version>.json) for a v* tag build
    (release/testing, told apart by pcsx_channel_of), and emu/<name>/nightly/<version>/ the same way for a
    develop-push build - name = pcsx-ab or pcsx-abnxt. The newest build per channel (nightly/testing/release)
    is kept, an older one of the same channel pruned (an older nightly the way the site prunes elsewhere -
    only the newest survives).

    emu/<name>/latest.json stays the shape it always was at its top level - {"version", "files", optionally
    "manifest"/"note"} - because make_win_package.sh (autobleem2/autobleem) and autobleem-appliance both read
    it that way (json.load(...)["files"]["win64"]["url"]) to build the Windows product; RELEASE-4 must not
    make either ship with no emulator. The top level is the newest *tag* build - release, else testing - what
    a package build should take; only when there is no tag build at all (a nightly-only tree) does the
    top level fall back to the nightly, so the file is never missing one while any build exists. The channels
    themselves sit beside it under "channels": {"release": build, "testing": build, "nightly": build} (a
    channel missing when there is no build for it) - what the download page's PS1 emulators tab reads.

    Returns the "channels" dict (unaffected by the compatibility shape above) - a build being {"version",
    "files": {plat: entry}, optionally "manifest"/"note"}."""
    root = os.path.join(repo, "emu", name)
    nightly_root = os.path.join(root, "nightly")

    tag_builds = _read_pcsx_builds(repo, base_url, name, root)
    tag_builds.pop("nightly", None)  # the nightly subdirectory itself is never a version folder
    nightly_builds = _read_pcsx_builds(repo, base_url, name, nightly_root)

    channels = {}
    keep_tag_versions = set()
    for channel in ("release", "testing"):
        versions = [v for v in tag_builds if pcsx_channel_of(v) == channel]
        if versions:
            newest = sorted(versions, key=pcsx_version_key)[-1]
            channels[channel] = tag_builds[newest]
            keep_tag_versions.add(newest)

    # nightly: the real nightly/ builds plus any legacy dated build still sitting directly under emu/<name>/
    # (pcsx_channel_of also calls those "nightly") - one shared pool, the newest of either wins
    legacy_nightly = {v: b for v, b in tag_builds.items() if pcsx_channel_of(v) == "nightly"}
    nightly_pool = dict(nightly_builds)
    nightly_pool.update(legacy_nightly)
    keep_nightly_version = None
    if nightly_pool:
        keep_nightly_version = sorted(nightly_pool, key=pcsx_version_key)[-1]
        channels["nightly"] = nightly_pool[keep_nightly_version]
        if keep_nightly_version in legacy_nightly:
            keep_tag_versions.add(keep_nightly_version)

    prune([os.path.join(root, v) for v in tag_builds if v not in keep_tag_versions], [], name + " build")
    keep_nightly_in_dir = keep_nightly_version if keep_nightly_version in nightly_builds else None
    prune([os.path.join(nightly_root, v) for v in nightly_builds if v != keep_nightly_in_dir],
          [], name + " nightly build")

    latest_path = os.path.join(root, "latest.json")
    if channels:
        # the top level is the newest tag build (release, else testing); only a nightly-only tree falls back
        # to the nightly - never a nightly at top level when a tag build exists
        top = channels.get("release") or channels.get("testing") or channels["nightly"]
        latest = dict(top)
        latest["channels"] = channels
        write_json(latest_path, latest)
    elif os.path.isfile(latest_path):
        # every build folder is gone (a `repo_publish.sh withdraw` of the sole build, with none republished
        # yet) - a stale latest.json would otherwise keep offering a build whose folder no longer exists
        os.remove(latest_path)
    return channels


#*******************************
# extensions
#*******************************
def extension_is_release(version):
    """1.0.0 is a release (a v* tag's build); 1.0.0-20260924-a13e56a is a development build of develop"""
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None


def index_extensions(repo, base_url):
    """extensions/<name>/<version>/: an extension's packages as its CI publishes them (EXTENSION_RE). Kept: the
    newest release, and the newest development build published after it - an older build of either goes.
    extensions/<name>/latest.json says which, with every file. Returns {name: {"release": build,
    "development": build}}, a build being {"version", "files": [entry + "pkg" + "plat"]}; either may be absent."""
    out = {}
    root = os.path.join(repo, "extensions")
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        eroot = os.path.join(root, name)
        if not os.path.isdir(eroot):
            continue
        builds = {}
        for version in os.listdir(eroot):
            folder = os.path.join(eroot, version)
            if not os.path.isdir(folder):
                continue
            files, published = [], 0
            for path in data_files(folder):
                m = EXTENSION_RE.match(os.path.basename(path))
                if not m or m.group("version") != version:
                    continue
                files.append(dict(file_entry(repo, base_url, path), pkg=m.group("pkg"), plat=m.group("plat")))
                stamp = path + ".sha256"
                published = max(published, os.path.getmtime(stamp if os.path.isfile(stamp) else path))
            if files:
                builds[version] = {"version": version, "files": files, "published": published}
        if not builds:
            continue
        releases = [v for v in builds if extension_is_release(v)]
        release = max(releases, key=lambda v: (tuple(int(x) for x in v.split(".")), builds[v]["published"])) \
            if releases else None
        devs = [v for v in builds if not extension_is_release(v)
                and (release is None or builds[v]["published"] > builds[release]["published"])]
        dev = max(devs, key=lambda v: builds[v]["published"]) if devs else None
        prune([os.path.join(eroot, v) for v in builds if v not in (release, dev)], [], name + " build")
        entry = {}
        if release:
            entry["release"] = {k: builds[release][k] for k in ("version", "files")}
        if dev:
            entry["development"] = {k: builds[dev][k] for k in ("version", "files")}
        write_json(os.path.join(eroot, "latest.json"), entry)
        out[name] = entry
    return out


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


MANUAL_LANGUAGES = {
    "en": "English", "pl": "Polski", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano",
    "pt-br": "Português (Brasil)", "zh-cn": "简体中文", "nl": "Nederlands", "sv": "Svenska", "da": "Dansk",
    "fi": "Suomi", "cs": "Čeština", "sk": "Slovenčina", "ro": "Română", "tr": "Türkçe", "oc": "Occitan",
}
# the folder code is one or two hyphen-joined parts (pt-br, zh-cn); a lazy stem so "pt-br"/"zh-cn" are not
# split at their own hyphen (a greedy stem would back off to the shortest suffix, "br"/"cn" alone - wrong)
MANUAL_RE = re.compile(r"^(?P<stem>.+?)-(?P<lang>[a-z]{2}(?:-[a-z]{2})?)\.pdf$")


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
# one development build on the site (the owner's call, 2026-09-23 - the build server's disk ran full;
# PLATFORM-10, 2026-09-27 - the disk ran full again, to three kept builds, one of them a duplicate). A run
# used to publish in pieces with each piece indexed as it arrived, so a fallback kept the newest older folder
# with packages (or with images) while the newest lacked either, rather than leave the launcher's update or
# Imager's nightly list pointing at nothing. That per-piece fallback is gone (PLATFORM-10): since the
# `--partial` + `.incomplete` marker mechanism (2026-09-23, autobleem-appliance's assemble.yml - see
# publish-nightly's `needs`/`if`, which only removes the marker and triggers this index once assemble, image
# and publish-release have all succeeded or been legitimately skipped for that run), a folder is never
# indexed at all until it already has every piece *that run built* - packages and images together, in one
# atomic step.
#
# But "every piece that run built" is not always everything: assemble.yml's workflow_dispatch can ask for a
# subset of platforms (`platforms`) or skip the three images (`images: false`) - a legitimate, complete
# publish of a smaller build. If the components changed since the last nightly, that gets its own new
# version (plan's -n<hash>) and publish-nightly de-marks it same as a full run, leaving a folder with only
# some platforms' packages and/or no images at all. Keeping only that one folder would then point the
# rpi/pcusb launchers' update, and Imager's nightly list, at nothing for those platforms until a full build
# comes along - so a second rule (PLATFORM-10 review): while the newest folder is partial, the newest older
# FULL folder is also kept, and nothing else - a normal (full) night still leaves exactly one folder on disk.
# `nightly_folder_is_full()` reads the same sources.json the plan job's own skip check reads (the `printf
# '{"sources": ...` in publish-nightly, the fields it looks for around assemble.yml's skip logic): a missing
# sources.json, or one without "images"/"platforms", predates those keys and counts as full, exactly as the
# plan job treats it.
NIGHTLY_KEEP = 1

# assemble.yml's plan job, workflow_dispatch's `platforms` left empty: "rpi-armhf rpi-arm64 pcusb psc win"
NIGHTLY_FULL_PLATFORMS = frozenset(["rpi-armhf", "rpi-arm64", "pcusb", "psc", "win"])


def nightly_folder_is_full(folder):
    """Whether `folder` was published as a full build - every platform, with images - per its sources.json
    (publish-nightly's `images`/`platforms` fields), the same rule the plan job's own skip check uses. No
    sources.json, or one without both keys, predates them and counts as full."""
    path = os.path.join(folder, "sources.json")
    if not os.path.isfile(path):
        return True
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return True
    if "images" not in data or "platforms" not in data:
        return True
    if not data["images"]:
        return False
    return NIGHTLY_FULL_PLATFORMS.issubset(str(data["platforms"]).split())


def nightly_folders_to_keep(folders, is_full=nightly_folder_is_full):
    """The newest of `folders` (oldest first), plus the newest older FULL one while the newest is itself only
    a partial build (some platforms, or no images) - see the module comment above."""
    if not folders:
        return []
    newest = folders[-1]
    if is_full(newest):
        return [newest]
    older_full = [f for f in folders[:-1] if is_full(f)]
    return ([older_full[-1]] if older_full else []) + [newest]


# repo_publish.sh --partial leaves it in nightly/<version>/ until the run's last publish takes it away
INCOMPLETE_MARKER = ".incomplete"
UNFINISHED_MAX_AGE = 2 * 24 * 3600  # seconds since the last file arrived


def unfinished_nightlies(folders, is_incomplete, published, now):
    """The folders still being published, and those of them abandoned (nothing new for UNFINISHED_MAX_AGE)."""
    unfinished = [f for f in folders if is_incomplete(f)]
    stale = [f for f in unfinished if now - published(f) > UNFINISHED_MAX_AGE]
    return [f for f in unfinished if f not in stale], stale


# repo_publish.sh --partial stages a run's pieces into <section>/<version>.partial/ - never into the version's own
# folder, so a finished build of the same version is not touched; the run's last publish moves them over it
PARTIAL_SUFFIX = ".partial"


def newest_file_time(folder):
    """The mtime of the newest file inside `folder` (any depth); the folder's own when it holds none."""
    times = []
    for here, _dirs, names in os.walk(folder):
        times.extend(os.path.getmtime(os.path.join(here, n)) for n in names)
    return max(times) if times else os.path.getmtime(folder)


def partial_folders(root):
    """The <version>.partial staging folders under `root`."""
    return sorted(os.path.join(root, v) for v in os.listdir(root)
                  if v.endswith(PARTIAL_SUFFIX) and os.path.isdir(os.path.join(root, v)))


def index_nightly(repo, base_url, section="nightly"):
    """nightly/<version>/ - the development builds of develop (the nightly run, or one started by hand): the
    packages a release has, named by `git describe` (v2.0.0-alpha2-14-gabc1234), and the images when that run
    made them. nightly_folders_to_keep() decides what stays; each folder gets release.json + SHA256SUMS,
    nightly/latest.json is the newest with packages. An installed launcher's update check never reads this - it stays on
    releases/ (latest.json, unstable.json).
    section="preview" (PLATFORM-20) indexes preview/<version>/ the same way - a feature branch's build, started from
    the admin panel: preview/latest.json (psc kept: a console on the Preview channel reads it) and
    rpi-imager/os_list-preview.json. The download page lists the newest one beside the nightly."""
    root = os.path.join(repo, section)
    if not os.path.isdir(root):
        return []

    def published(folder):
        # the newest sidecar in the folder is when the build went up (the folder's own mtime is not reliable)
        times = [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder) if n.endswith(".sha256")]
        return max(times) if times else os.path.getmtime(folder)

    # a .partial staging folder is never a build: not listed, not counted; one abandoned for two days goes
    now = datetime.now().timestamp()
    prune([p for p in partial_folders(root) if now - newest_file_time(p) > UNFINISHED_MAX_AGE], [],
          "abandoned partial development build")
    folders = sorted((os.path.join(root, v) for v in os.listdir(root)
                      if os.path.isdir(os.path.join(root, v)) and not v.endswith(PARTIAL_SUFFIX)),
                     key=published)
    # a build still being published (repo_publish.sh --partial) is not a nightly yet: it neither replaces the one
    # before nor is listed until its run's last publish; one a run left unfinished goes after two days
    unfinished, stale = unfinished_nightlies(
        folders, lambda f: os.path.exists(os.path.join(f, INCOMPLETE_MARKER)), published, datetime.now().timestamp())
    prune(stale, [], "unfinished development build")
    folders = [f for f in folders if f not in unfinished and f not in stale]
    keep = nightly_folders_to_keep(folders)
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
            "channel": "dev" if section == "nightly" else section,
            "date": datetime.fromtimestamp(published(folder), timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "files": files,
            "images": images,
            "other_files": others,
        }
        write_json(os.path.join(folder, "release.json"), build)
        builds.append(build)
    # what the launcher's update and the installers read: the newest build that has packages (one still being
    # published may have only its images so far)
    path = os.path.join(root, "latest.json")
    with_files = [b for b in builds if b["files"]] or builds
    if with_files:
        write_json(path, with_files[-1])
    elif os.path.isfile(path):
        os.remove(path)
    # the newest Pi images as Imager's third repository (the image job publishes make_rpi_image.sh's
    # rpi_imager_repo.json next to them) - from the newest build that has them, see nightly_folders_to_keep
    with_images = [b for b in builds if any(a in ("armhf", "arm64") for a in b["images"])]
    newest = with_images[-1] if with_images else None
    write_imager_list(repo, base_url, "os_list-%s.json" % section,
                      os.path.join(root, newest["version"], "rpi_imager_repo.json") if newest else None,
                      {a: f for a, f in (newest or {}).get("images", {}).items() if a in ("armhf", "arm64")},
                      section)
    return builds


#*******************************
# channels.json - the release channels the PC installers offer
#*******************************
# The PC Installer and the Flasher read <site>/channels.json to fill their channel list, so a new channel (the
# preview one) shows up without a new program. Each entry: id, label, index (the channel's own latest json, the
# stick package's file), images (only when the PC stick image lives in another file - pc/images/<id>.json) and
# unstable. Stable first; a channel is listed only when its json exists. The channels' own jsons are not touched.
PREVIEW_VERSION_RE = re.compile(r"^preview-(?P<branch>.+)-[0-9a-f]{6,}$")


def write_channels(repo):
    """channels.json at the site's root; returns the channel list. Nothing to list = the file is removed."""
    def has(path):
        return os.path.isfile(os.path.join(repo, *path.split("/")))

    channels = []

    def add(cid, label, index, unstable, images=None):
        if not has(index):
            return
        entry = {"id": cid, "label": label, "index": index, "unstable": unstable}
        if images and has(images):
            entry["images"] = images
        channels.append(entry)

    add("release", "Release", "releases/latest.json", False, "pc/images/release.json")
    add("testing", "Testing", "releases/unstable.json", False, "pc/images/testing.json")
    add("nightly", "Nightly", "nightly/latest.json", True)
    label = "Preview"
    if has("preview/latest.json"):
        try:
            with open(os.path.join(repo, "preview", "latest.json"), encoding="utf-8") as f:
                m = PREVIEW_VERSION_RE.match(json.load(f).get("version", ""))
            if m:
                label = "Preview (%s)" % m.group("branch")
        except (OSError, ValueError, AttributeError):
            pass
    add("preview", label, "preview/latest.json", True)
    path = os.path.join(repo, "channels.json")
    if channels:
        write_json(path, {"version": 1, "channels": channels})
    elif os.path.isfile(path):
        os.remove(path)
    return channels


#*******************************
# the landing page
#*******************************
# The ab2.0.0 look (graphite, cyan lines, magenta for the selected thing, cut corners, Red Hat Text), designed in
# autobleem-design www/ - everything under /assets, staged by tools/repo_assets.py.
PAGE_CSS = """
/* AutoBleem 2 download site - the ab2.0.0 look (graphite, cyan lines, magenta focus, cut corners, Red Hat Text).
   A drop-in for repo_index.py's PAGE_CSS: every class the generator writes keeps its name; new ones are marked NEW.
   Cut corners: clip-path on the box, the 1 px line drawn by its ::before (the same polygon, 1 px larger) -
   see www/README.md "Cut corners". Corners cut: top-right and bottom-left, like the theme's tiles. */
@font-face{font-family:"Red Hat Text";src:url(/assets/RedHatText-Medium.ttf) format('truetype');font-weight:500;font-display:swap}
@font-face{font-family:"Red Hat Text";src:url(/assets/RedHatText-SemiBold.ttf) format('truetype');font-weight:600;font-display:swap}
:root{
  --bg:#12161c;--panel:#262e38;--panel-top:#2e3742;--panel-bot:#212831;--panel-glass:rgba(33,40,49,.88);
  --cyan:#36d9e0;--line:rgba(54,217,224,.34);--line-soft:rgba(54,217,224,.14);--magenta:#ff46aa;
  --ink:#e8eef4;--dim:#9aa8b6;--steel:#aab8c6;
  --rel:#58e0a0;--pre:#ffc857;--dev:#b9a0ff;--warn:#ff8a65;
  --cut:12px;--cut-s:7px}
*{box-sizing:border-box}
html{scroll-padding-top:4.2rem}
body{margin:0;font-family:"Red Hat Text","Segoe UI",system-ui,sans-serif;font-weight:500;color:var(--ink);line-height:1.5;
  background:var(--bg) url(/assets/background.jpg) center top/cover fixed}
body:before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:linear-gradient(180deg,rgba(18,22,28,.55) 0,rgba(18,22,28,.82) 60%,rgba(18,22,28,.92) 100%)}
a{color:var(--cyan);text-decoration:none}a:hover{color:#fff;text-decoration:underline}

/* the cut-corner box: .cut on any block (panels, notices, buttons) */
.cut,.panel,.notice,details.inputs,.status,a.big,.hero .in:before{
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}

/* the top bar */
header.top{position:sticky;top:0;z-index:5;background:rgba(18,22,28,.9);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line)}
header.top:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;
  background:linear-gradient(90deg,var(--magenta) 0 56px,transparent 56px 64px,var(--cyan) 64px,rgba(54,217,224,.2) 75%,transparent)}
header.top .bar{max-width:68rem;margin:0 auto;padding:.5rem 1rem;display:flex;align-items:center;gap:1rem}
header.top .brand{display:flex;align-items:center;gap:.6rem;color:#fff;font-size:1.1rem;font-weight:600;letter-spacing:.06em}
header.top .brand img{height:32px;width:auto}
header.top .brand span{color:var(--dim);font-weight:500;font-size:.95rem;letter-spacing:.02em}
header.top .brand:hover{text-decoration:none}
header.top nav{margin-left:auto;display:flex;gap:1.2rem;font-size:.95rem}
header.top nav a{color:var(--steel);white-space:nowrap}
header.top .brand{white-space:nowrap}
header.top nav a:hover,header.top nav a.on{color:var(--cyan);text-decoration:none}

/* the banner: one line left, the C3 logo right */
.hero{border-bottom:1px solid var(--line-soft)}
.hero .in{max-width:68rem;margin:0 auto;padding:0 1rem;height:clamp(96px,14vw,168px);display:flex;align-items:center;gap:1rem}
.hero p{flex:1;margin:0;font-size:clamp(1rem,2vw,1.35rem);color:#fff;max-width:34rem}
.hero p:after{content:"";display:block;width:4.5rem;height:3px;margin-top:.7rem;
  background:linear-gradient(90deg,var(--cyan) 0 72%,transparent 72% 78%,var(--magenta) 78%)}
.hero img{height:72%;width:auto;margin-left:auto;display:block}

main{max-width:68rem;margin:0 auto 3rem;padding:0 1rem}
/* the 1 px frame of a cut box: the box's ::after is a ring - the outer cut polygon with the same polygon one px
   in cut out of it (evenodd), painted --ring. One shape in one coordinate space, so the frame is whole on the
   straight edges and the diagonals at any size (a box-shadow or a second layer 1 px in snapped to other pixels
   than the clip and lost an edge). --cut is the box's own cut; every ring box sets --ring and --cut. */
.panel,.notice,details.inputs,.status,.chan,td.file a,a.dl,button.copy,nav.subtabs a,a.big{position:relative}
.panel:after,.notice:after,details.inputs:after,.status:after,.chan:after,td.file a:after,a.dl:after,button.copy:after,
nav.subtabs a:after,a.big:after{content:"";position:absolute;inset:0;pointer-events:none;background:var(--ring);
  clip-path:polygon(evenodd,0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)),0 0,
    1px 1px,calc(100% - 1px - var(--cut) + .59px) 1px,calc(100% - 1px) calc(1px + var(--cut) - .59px),calc(100% - 1px) calc(100% - 1px),
    calc(1px + var(--cut) - .59px) calc(100% - 1px),1px calc(100% - 1px - var(--cut) + .59px),1px 1px)}
.panel,.notice,details.inputs,.status{isolation:isolate;--ring:var(--line);
  background:var(--fill,linear-gradient(180deg,var(--panel-top),var(--panel-bot)))}
.panel{padding:1.1rem 1.3rem;margin:1rem 0}
.lede{color:var(--dim);margin:1.1rem 0 .4rem;font-size:.98rem}
.lede b{color:var(--ink);font-weight:600}
h1{font-weight:600;font-size:1.7rem;margin:0 0 .4rem;color:#fff}
h2{font-weight:600;font-size:1.15rem;letter-spacing:.05em;margin:0 0 .6rem;color:var(--cyan);text-transform:uppercase}
h2 small,h1 small{font-size:.75em;color:var(--dim);letter-spacing:0;margin-left:.5rem;text-transform:none;font-weight:500}
h3{font-weight:600;font-size:.95rem;margin:1rem 0 .4rem;color:var(--steel)}
h3 small{font-weight:500}
p{margin:.4rem 0 .8rem}
ul,ol{padding-left:1.3rem}li{margin:.3rem 0}
ul.what{margin:.3rem 0 .9rem}ul.what b{color:var(--ink);font-weight:600}
code{font-family:ui-monospace,Consolas,monospace;font-size:.88em;color:#fff;background:rgba(0,0,0,.28);
  padding:.05em .35em;border-radius:2px}

/* the one table style */
table{border-collapse:collapse;width:100%;margin:.4rem 0 .2rem}
td,th{text-align:left;padding:.5rem .55rem;border-bottom:1px solid var(--line-soft);vertical-align:middle}
th{font-weight:600;color:var(--dim);font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;padding-top:.2rem}
tr:last-child td{border-bottom:0}
tbody tr:hover td{background:rgba(54,217,224,.05)}
td.what small{display:block;color:var(--dim);font-size:.83rem;line-height:1.35;margin-top:.1rem}
td.what img.icon{float:left;width:44px;height:44px;object-fit:contain;margin:.1rem .75rem .1rem 0;
  clip-path:polygon(0 0,calc(100% - var(--cut-s)) 0,100% var(--cut-s),100% 100%,var(--cut-s) 100%,0 calc(100% - var(--cut-s)))}
td.file{white-space:nowrap}
td.file a,a.dl{display:inline-block;padding:.22rem .8rem;font-size:.88rem;font-weight:600;color:var(--cyan);
  background:rgba(54,217,224,.1);--ring:var(--line);--cut:var(--cut-s);
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}
td.file a:hover,a.dl:hover{background:rgba(255,70,170,.16);--ring:var(--magenta);color:#fff;text-decoration:none}
td.file a:before{content:"\\2193  "}
td.size{white-space:nowrap;color:var(--dim);text-align:right}
th.size{text-align:right}
td.when{white-space:nowrap;color:var(--dim);font-size:.85em}
.chan{display:inline-block;white-space:nowrap;font-size:.76rem;font-weight:600;padding:.06rem .55rem;letter-spacing:.02em;
  color:var(--dim);--ring:currentColor;--cut:5px;
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}
.chan.rel{color:var(--rel)}.chan.pre{color:var(--pre)}.chan.dev{color:var(--dev)}
.badge{display:inline-block;font-size:.7rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:.02rem .45rem;
  background:rgba(255,138,101,.16);color:var(--warn);margin-left:.4rem;vertical-align:1px}
.warn{color:var(--warn)}
.older{color:var(--dim);font-size:.9rem}

/* Build inputs, folded */
details.inputs{margin:1rem 0;--ring:var(--line-soft);--fill:rgba(18,22,28,.72)}
details.inputs>summary{cursor:pointer;padding:.75rem 1.3rem;color:var(--dim);list-style:none;display:flex;gap:.6rem;align-items:baseline}
details.inputs>summary::-webkit-details-marker{display:none}
details.inputs>summary:before{content:"\\25B8";color:var(--cyan);transition:transform .15s}
details.inputs[open]>summary:before{transform:rotate(90deg)}
details.inputs>summary b{color:var(--ink);font-weight:600}
details.inputs>div{padding:0 1.3rem 1rem}

/* tabs: the selected one magenta, like the launcher's focus */
h2.plat{margin:2rem 0 .2rem;padding-bottom:.3rem;border-bottom:1px solid var(--line);color:#fff;font-size:1.35rem;text-transform:none}
nav.tabs{display:flex;flex-wrap:wrap;gap:.3rem;margin:1.2rem 0 0;border-bottom:1px solid var(--line)}
nav.tabs a{position:relative;padding:.55rem 1.1rem;color:var(--steel);font-size:.98rem;font-weight:600;margin-bottom:-1px;
  clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,0 100%)}
nav.tabs a:hover{color:#fff;text-decoration:none;background:rgba(54,217,224,.07)}
nav.tabs a.active{background:linear-gradient(180deg,var(--panel-top),var(--panel-bot));color:#fff;
  box-shadow:inset 0 3px 0 var(--magenta)}
body.js section.tab{display:none}
body.js section.tab.active{display:block}
body.js section.tab h2.plat{display:none}
nav.subtabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:1rem 0 .4rem}
nav.subtabs a{padding:.28rem .95rem;color:var(--steel);font-size:.9rem;font-weight:600;background:rgba(18,22,28,.6);
  --ring:var(--line-soft);--cut:var(--cut-s);
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}
nav.subtabs a:hover{color:#fff;text-decoration:none}
nav.subtabs a.active{color:#fff;background:rgba(255,70,170,.14);--ring:var(--magenta)}
h3.subtab{font-size:1.15rem;color:#fff;margin:1.4rem 0 .2rem}
body.js section.subtab{display:none}
body.js section.subtab.active{display:block}
body.js section.subtab h3.subtab{display:none}

/* something to copy into another program */
.notice{display:flex;align-items:center;flex-wrap:wrap;gap:.5rem .8rem;margin:.8rem 0 1rem;padding:.75rem 1rem .75rem 1.2rem;
  --fill:linear-gradient(90deg,#1d3a42,#1f2a33 60%);
  background:linear-gradient(var(--cyan),var(--cyan)) 0 0/3px calc(100% - var(--cut)) no-repeat,var(--fill)}
.notice .label{flex-basis:100%;color:var(--dim);font-size:.88rem}
.notice .label b{color:var(--ink);font-weight:600}
.notice .nrow{display:flex;align-items:center;gap:.8rem;width:100%}
.notice .nrow .chan{min-width:5.2rem;text-align:center}
.notice code{flex:1;min-width:0;overflow-wrap:anywhere;font-size:.9rem;padding:.35rem .6rem}
button.copy{font:inherit;font-size:.86rem;font-weight:600;color:var(--cyan);background:rgba(54,217,224,.1);border:0;
  --ring:var(--line);--cut:var(--cut-s);padding:.3rem .95rem;cursor:pointer;
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}
button.copy:hover{background:rgba(255,70,170,.16);--ring:var(--magenta);color:#fff}
button.copy.done{color:var(--rel);--ring:var(--rel)}
footer{color:var(--dim);font-size:.8rem;text-align:center;margin-top:2rem;padding:0 1rem}

/* NEW - the splash page (/) */
body.splash{display:flex;flex-direction:column;min-height:100vh}
body.splash main{flex:1;max-width:46rem;text-align:center;padding-top:clamp(1.5rem,6vh,4.5rem)}
.splash .logo{width:min(440px,86vw);height:auto;display:block;margin:0 auto .4rem}
.splash h1{font-size:clamp(1.7rem,4.6vw,2.6rem);margin:.6rem 0 .3rem;letter-spacing:.01em}
.splash .sub{color:var(--steel);font-size:clamp(1rem,2.2vw,1.15rem);margin:0 auto 1.6rem;max-width:34rem}
.status{text-align:left;max-width:30rem;margin:0 auto 1.8rem;padding:.9rem 1.2rem}
.status h2{font-size:.78rem;letter-spacing:.14em;margin:0 0 .45rem;color:var(--dim)}
.status ul{list-style:none;margin:0;padding:0}
.status li{display:flex;align-items:center;gap:.7rem;margin:0;padding:.42rem 0;border-top:1px solid var(--line-soft)}
.status li:first-child{border-top:0}
.status li .k{flex:1;color:var(--ink)}
.status li .k small{display:block;color:var(--dim);font-size:.8rem}
.status li .chan{min-width:6.6rem;text-align:center}
.status li .dot{width:8px;height:8px;border-radius:50%;background:var(--rel);box-shadow:0 0 8px var(--rel);flex:none}
.status li .dot.next{background:transparent;box-shadow:inset 0 0 0 2px var(--pre)}
a.big{display:inline-flex;align-items:center;gap:.7rem;padding:.95rem 2.1rem;font-size:1.15rem;font-weight:600;color:#fff;
  letter-spacing:.02em;background:linear-gradient(180deg,#ff5cb6,#d9358f);--ring:rgba(255,255,255,.25);
  --cut:14px}
a.big:hover{background:linear-gradient(180deg,#ff73c1,#e8409c);text-decoration:none}
a.big:before{content:"\\2193";font-size:1.25rem}
.splash .thanks{color:var(--steel);margin:1.8rem auto .9rem;max-width:32rem;font-size:.95rem}
.splash .thanks b{color:#fff;font-weight:600}
a.support{position:relative;display:inline-block;width:252px;height:48px;line-height:0}
a.support img{width:252px;height:48px}
a.support:after{content:"";position:absolute;left:-10px;top:-10px;width:272px;height:68px;opacity:0;pointer-events:none;
  background:url(/assets/button-support-hover.png) 0 0/272px 68px no-repeat;
  background-image:-webkit-image-set(url(/assets/button-support-hover.png) 1x,url(/assets/button-support-hover@2x.png) 2x);
  background-image:image-set(url(/assets/button-support-hover.png) 1x,url(/assets/button-support-hover@2x.png) 2x)}
a.support:hover:after{opacity:1}
a.support:hover img{opacity:0}
.splash .more{margin-top:1.4rem;font-size:.9rem;color:var(--dim)}
.splash .more a{margin:0 .5rem}

@media (max-width:640px){
  td.when,th.when,td.size,th.size{display:none}
  .chan{white-space:normal;word-break:break-all}
  td.file a{padding:.2rem .55rem}
  .panel,details.inputs>div{padding-left:.8rem;padding-right:.8rem}
  nav.tabs a{padding:.45rem .7rem;font-size:.9rem}
  td,th{padding:.45rem .35rem}
  header.top nav{gap:.7rem;font-size:.85rem}
  header.top .brand span{display:none}
  .hero img{display:none}
  a.big{padding:.85rem 1.4rem;font-size:1.05rem}
  .status{padding:.8rem .9rem}
  .status li .chan{min-width:0}
}
@media (max-width:480px){
  header.top .bar{gap:.6rem}
  header.top .brand{font-size:0;gap:0}  /* the emblem alone; the logo is on the page */
  header.top nav{gap:.85rem;font-size:.84rem}
}
"""


# set by index_testplans: the site has test plans, so every page's bar links the Testing pages
HAS_TESTING = False


def page_head(title, tagline, extra_css=""):
    """The top of every inner page: the document head, a slim bar with the emblem and the links, and a short
    banner - the page's line on the left, the C3 logo on the right - so the first screen shows what to download.
    The brand goes to the splash (/), the downloads and the manual to /repository/."""
    e = html.escape
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s</title>%s<style>%s%s</style>%s</head><body>"
            "<header class=\"top\"><div class=\"bar\"><a class=\"brand\" href=\"/\"><img src=\"/assets/emblem.png\" "
            "srcset=\"/assets/emblem@2x.png 2x\" alt=\"\">AutoBleem 2 <span>Downloads</span></a><nav>"
            "<a href=\"/store/\">Store</a><a href=\"/repository/#manuals\">Manual</a><a href=\"/releases/\">All files</a>"
            "%s<a href=\"https://github.com/autobleem2\">GitHub</a></nav></div></header>"
            "<div class=\"hero\"><div class=\"in\"><p>%s</p><img src=\"/assets/logo.png\" "
            "srcset=\"/assets/logo@2x.png 2x\" alt=\"AutoBleem 2\"></div></div>"
            % (e(title), ICON_LINKS, PAGE_CSS, extra_css, COPY_SCRIPT,
               "<a href=\"/testing/\">Testing</a>" if HAS_TESTING else "", e(tagline)))


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


def chan_pill(text, cls=""):
    """a version as a channel pill: rel release, pre pre-release, dev development build"""
    return "<span class=\"chan %s\">%s</span>" % (cls, html.escape(text)) if text else ""


def file_row(label, f, version="", cls="", note="", badge="", icon=""):
    """one file: what it is (a note under it, a badge after it, a picture before it), its version as a channel
    pill, the file, its size and the day it went up (the full time on hover). The file is a button named by its
    type, the whole name on hover - the names carry the version again and wrapped mid-word in a narrow column"""
    e = html.escape
    when = f.get("uploaded", "")
    m = re.search(r"\.(tar\.gz|img\.xz|zip|exe|txt|db|pdf|chd|pbp|7z|mod)$", f["name"])
    return ("<tr><td class=\"what\">%s%s%s%s</td><td>%s</td><td class=\"file\"><a href=\"%s\" title=\"%s\">%s</a></td>"
            "<td class=\"size\">%s</td><td class=\"when\" title=\"%s\">%s</td></tr>" % (
                "<img class=\"icon\" src=\"%s\" alt=\"\" loading=\"lazy\">" % e(icon) if icon else "",
                e(label), "<span class=\"badge\">%s</span>" % e(badge) if badge else "",
                "<small>%s</small>" % note if note else "", chan_pill(version, cls),
                e(f["url"]), e(f["name"]), e(m.group(1) if m else "file"), human(f["size"]), e(when), e(when[:10])))


def files_table(rows):
    if not rows:
        return ""
    body = "".join(rows)
    if "class=\"chan" not in body:
        # nothing in it has a version (the manuals, the cover databases): no empty column
        return ("<table><thead><tr><th>What</th><th>Download</th><th class=\"size\">Size</th><th class=\"when\">Date</th>"
                "</tr></thead><tbody>%s</tbody></table>" % body.replace("<td></td><td class=\"file\">", "<td class=\"file\">"))
    return ("<table><thead><tr><th>What</th><th>Version</th><th>Download</th><th class=\"size\">Size</th>"
            "<th class=\"when\">Date</th></tr></thead><tbody>%s</tbody></table>" % "".join(rows))


def folded_inputs(summary, body):
    """build inputs, folded: a user installs from the table above, the installers and CI from these"""
    return ("<details class=\"inputs\"><summary><b>Build inputs</b> %s</summary><div>%s</div></details>"
            % (summary, body))


def render_index(base_url, releases, builds, cores, images, dbs, psc_builds, psc_cores, samples=None, psc_libs=None,
                 psc_apps=None, psc_bios=None, pc=None, pcsx=None, manuals=None, psc_kernel=None, nightly=None,
                 store=None, preview=None):
    """The page: a tab per platform, each leading with what a user installs from (the installer, the images,
    the packages) in one table across the three channels - the latest release, the one pre-release, the
    newest development build - and, folded away under it, the build inputs the installers, the image build and
    the CI fetch from here (RetroArch builds, cores, libraries, the kernel payload, the cover databases)."""
    e = html.escape

    chan, row, table, inputs = chan_pill, file_row, files_table, folded_inputs

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
    # a feature branch's build (PLATFORM-20, started from the admin panel): the same tables, its own pill text
    preview = [b for b in (preview or []) if b.get("files") or b.get("images")]
    if preview:
        channels.append((preview[-1], "dev", preview[-1]["version"]))

    def release_rows(kinds, short=None, notes=None):
        """the packages of these kinds in each channel - release, pre-release, development build"""
        short = short or {}
        notes = notes or {}
        out = []
        for which, cls, text in channels:
            for kind, _, kind_title in PACKAGE_KINDS:
                if kind in kinds and kind in which["files"]:
                    out.append(row(short.get(kind, kind_title), which["files"][kind], text, cls,
                                   note=notes.get(kind, "")))
        return out

    def dev_images(titles):
        """the newest development build's images, when that run made any (index_nightly: armhf, arm64, pc-i386),
        and the newest preview's"""
        out = []
        for dev, text in ([(nightly[-1], "dev " + nightly[-1]["version"])] if nightly else []) + \
                         ([(preview[-1], preview[-1]["version"])] if preview else []):
            out += [row(title, dev["images"][key], text, "dev")
                    for key, title in titles if key in (dev.get("images") or {})]
        return out

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
               "not work; <b>preview-...</b> a build of work in progress, for whoever tests it). Every file has a <code>.sha256</code> next to it; "
               "<a href=\"/releases/latest.json\">releases/latest.json</a> is the machine-readable list.</p>")

    # ---- PlayStation Classic ----
    out.append("<h2 class=\"plat\" id=\"psc\">PlayStation Classic</h2>")
    out.append("<div class=\"panel\"><h2>Install</h2>"
               "<p>Set the console up from a Windows PC: unzip the installer, plug in a USB stick, run "
               "<code>AutoBleemInstaller.exe</code>. It prepares the stick (FAT32, named <code>SONY</code>), puts "
               "AutoBleem on it and fetches what you tick - the cover art and, if you want other systems, RetroArch "
               "with its cores, libraries, apps and BIOS files. Run it again to update: your games, saves, memory "
               "cards and settings stay.</p>")
    rows = release_rows(("installer", "psc-base", "psc-full", "psc"),
                        {"installer": "Installer for Windows",
                         "psc-base": "The stick as a zip, base (unzip onto a FAT32 stick named SONY)",
                         "psc-full": "The stick as a zip, full (unzip onto a FAT32 stick named SONY)",
                         "psc": "The stick as one zip (unzip onto a FAT32 stick named SONY)"},
                        {"psc-base": "AutoBleem without RetroArch, smaller. No BIOS files: add your own.",
                         "psc-full": "AutoBleem with RetroArch and its cores. No BIOS files: add your own."})
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
               "<a href=\"/repository/rpi-install.html\">Which image for which Pi, step by step.</a></p>"
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
               "of the stick becomes the games partition. <a href=\"/repository/pc-install.html\">Step by step.</a></p>" % how)
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
    if dbs or samples or pcsx or manuals or store:
        out.append("<h2 class=\"plat\" id=\"inputs\">Every platform</h2>")
    if store:
        # an App built for four systems is one item
        count = len({i["id"] for items in store.values() for i in items})
        out.append("<div class=\"panel\" id=\"store\"><h2>AutoBleem Store</h2><p>Apps and games the launcher's Store "
                   "installs with one press - %d %s today. <a href=\"/store/\">See what it offers &rarr;</a></p></div>"
                   % (count, "item" if count == 1 else "items"))
    if manuals:
        out.append("<div class=\"panel\" id=\"manuals\"><h2>User manual</h2>"
                   "<p>Installing on every platform, the launcher and its screens, the console tools.</p>")
        out.append(table([row(lang, f) for lang, f in manuals]) + "</div>")
    emu_rows = []
    for name, heading, blurb in EMULATORS:
        channels_of = (pcsx or {}).get(name) or {}
        # same three channels and pills as everywhere else on the page: release, the one pre-release
        # (here "testing" - a pre-release tag), the newest development build ("dev " + version, as the
        # top-level nightly channel is shown)
        for channel, cls, prefix in (("release", "rel", ""), ("testing", "pre", ""), ("nightly", "dev", "dev ")):
            b = channels_of.get(channel)
            if not b:
                continue
            text = prefix + b["version"]
            for plat, title in PCSX_PLATFORMS:
                if plat in b["files"]:
                    emu_rows.append(row("%s, %s" % (name, title), b["files"][plat], text, cls))
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
    out.append("<footer>Generated %s UTC &middot; theme: ab2.0.0</footer></main></body></html>"
               % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return "\n".join(out) + "\n"


# the Store's platforms, as its page shows them: key, tab, sub-tab (the two Raspberry Pi flavours share a tab)
STORE_PLATFORMS = [
    ("psc", "PlayStation Classic", ""),
    ("rpi", "Raspberry Pi", "32-bit"),
    ("rpi64", "Raspberry Pi", "64-bit"),
    ("pcusb", "PC USB stick", ""),
    ("win", "Windows", ""),
]


def render_store(base_url, store, extension=None, lanshare=None):
    """store/index.html: what the AutoBleem Store offers, a tab per system - the Store itself for that system
    (the extension's packages, index_extensions' "store"), then the Apps and the games in the downloads page's
    table (each with its picture, its description, author and licence), the catalog the Store reads folded
    under them - and a LAN server tab with abstored for each machine that serves, and LAN Share (pc-tools, the
    Windows app that puts games on it; index_extensions' "lanshare"). The page the site shows at /store/ instead
    of the bare file list."""
    e = html.escape
    extension = extension or {}

    def packages(pkg, plat, source=None):
        """the rows of one package for one platform: the release, then a newer development build"""
        rows = []
        for channel, cls in (("release", "rel"), ("development", "dev")):
            build = (extension if source is None else source).get(channel)
            for f in (build or {}).get("files", []):
                if f["pkg"] == pkg and f["plat"] == plat:
                    # the downloads page's labels: a release's version, "dev <version>" for a development build
                    rows.append((f, build["version"] if cls == "rel" else "dev " + build["version"], cls))
        return rows
    out = [page_head("AutoBleem Store", "Apps and games for AutoBleem, installed from the launcher.")]
    out.append("<main>")
    out.append("<p class=\"lede\">What the <b>AutoBleem Store</b> offers on each system. It is an extension of the "
               "launcher: <b>L2+R2 &rarr; Extensions &rarr; AutoBleem Store</b> installs these with one press, "
               "and keeps them up to date. The files are here too. Your own lists of downloads go in the Store's "
               "<b>Sources</b> tab. <a href=\"/repository/\">&larr; Downloads</a></p>")

    def section(platform):
        items = store.get(platform) or []
        body = []
        own = packages("ext_store", platform)
        if own:
            rows = [file_row("AutoBleem Store", f, version, cls) for f, version, cls in own]
            body.append("<div class=\"panel\"><h2>The Store itself</h2><p>Unzip it into the root of the stick "
                        "(the data partition on a Raspberry Pi or the PC stick): it adds "
                        "<code>Extensions/store/</code>. Then <b>L2+R2 &rarr; Extensions</b>.</p>%s</div>"
                        % files_table(rows))
        titles = {i["id"]: i["title"] for i in items}
        for kind, heading in (("app", "Apps"), ("pe", "PE Apps"), ("package", "Game data packages"), ("ps1", "Games")):
            rows = []
            for i in sorted((i for i in items if i["kind"] == kind), key=lambda i: i["title"].lower()):
                note = e(i.get("description", ""))
                credits = " &middot; ".join(e(x) for x in (i.get("author"), i.get("licence")) if x)
                type_name = STORE_CATEGORIES.get(i.get("category", ""))
                if kind == "pe":
                    # a PE App: its licence in words, and the link to the source it was built from (GPL items)
                    credits = " &middot; ".join(
                        x for x in (e(i.get("author", "")),
                                    "Licence: " + e(i["licence"]) if i.get("licence") else "",
                                    "<a href=\"%s\">Source code</a>" % e(i["source_url"]) if i.get("source_url")
                                    else "") if x)
                if type_name:
                    credits += (" &middot; " if credits else "") + "Type: " + type_name
                # what the item needs (packages spec, 8.2) and what a package holds
                hints = []
                if i.get("requires"):
                    hints.append("Needs: " + e(", ".join(titles.get(r, r) for r in i["requires"])))
                elif i.get("uses"):
                    hints.append("Needs game data: " + e(", ".join(i["uses"])))
                if i.get("provides"):
                    hints.append("Content: " + e(", ".join(i["provides"])))
                if hints:
                    credits += (" &middot; " if credits else "") + " &middot; ".join(hints)
                if credits:
                    note += ("<br>" if note else "") + credits
                for n, f in enumerate(i["files"]):
                    label = i["title"] if len(i["files"]) == 1 else "%s, disc %d" % (i["title"], f.get("disc", n + 1))
                    rows.append(file_row(label, f, i.get("version", "") if n == 0 else "", "rel",
                                         note if n == 0 else "", icon=i.get("image", "") if n == 0 else ""))
            if rows:
                intro = ""
                if kind == "pe":
                    intro = ("<p>Programs built from open source for the PlayStation Classic. The Store's <b>PE "
                             "Apps</b> tab installs them with one press; to install one by hand, copy its "
                             "<code>.mod</code> file into the <code>Mods/</code> folder of the stick. Each one "
                             "links the source it was built from.</p>")
                if kind == "package":
                    intro = ("<p>Game files as packages: the Store puts one in the <code>Packages/</code> folder of the "
                             "stick, and an engine that runs that kind of game offers it in its picker.</p>")
                body.append("<div class=\"panel\"><h2>%s</h2>%s%s</div>" % (heading, intro, files_table(rows)))
        if not items:
            body.append("<div class=\"panel\"><p>%s</p></div>" % ("No Apps or games for this system yet." if own
                                                                  else "Nothing for this system yet."))
        if platform in store:
            catalog = "%s/store/%s/catalog.json" % (base_url, platform)
            body.append(folded_inputs("the catalog the Store reads",
                                      "<p><a href=\"%s\">%s</a> - JSON, every file with its size and SHA-256.</p>"
                                      % (e(catalog), e(catalog))))
        return "".join(body)

    shown = [p for p in STORE_PLATFORMS if p[0] in store or p[0] != "win" or packages("ext_store", p[0])]
    tabs = []
    for key, tab, sub in shown:
        if tab not in tabs:
            tabs.append(tab)
    for tab in tabs:
        members = [(key, sub) for key, t, sub in shown if t == tab]
        out.append("<h2 class=\"plat\" id=\"%s\">%s</h2>" % (members[0][0] if len(members) == 1 else
                                                              re.sub(r"[^a-z]", "", tab.lower()), e(tab)))
        if len(members) == 1:
            out.append(section(members[0][0]))
        else:
            for key, sub in members:
                out.append("<h3 class=\"subtab\" id=\"%s\">%s</h3>%s" % (key, e(sub), section(key)))
    # abstored, the Store's LAN server: for the machine that holds the games, not the one that plays them
    server = [file_row(label, f, version, cls) for plat, label in ABSTORED_PLATFORMS
              for f, version, cls in packages("abstored", plat)]
    share = [file_row("LAN Share for Windows", f, version, cls)
             for f, version, cls in packages("lanshare", "windows-x86_64", lanshare or {})]
    if server or share:
        out.append("<h2 class=\"plat\" id=\"lanserver\">LAN server</h2>")
    if server:
        out.append("<div class=\"panel\"><h2>abstored</h2><p>Shares a folder of your own PS1 games with the "
                   "Store on your home network: run it on the PC, NAS or Raspberry Pi that holds the games, then "
                   "add <code>http://&lt;that machine&gt;:8124/store.tsv</code> in the Store's <b>Sources</b> "
                   "tab. It only reads the folder unless it is started with <code>--allow-uploads</code> (for "
                   "LAN Share, below). Plain HTTP, for a home network only.</p>%s</div>" % files_table(server))
    if share:
        out.append("<div class=\"panel\"><h2>LAN Share</h2><p>The Windows app that puts games on that server: "
                   "it publishes the games in a folder on the PC, and reads a PS1 disc in the PC's drive into a "
                   "<code>.bin</code>/<code>.cue</code> and publishes it - through the server's network share, "
                   "or uploaded with its token. It shows what the server has, skips what is there already, and "
                   "takes games off it (into a <code>.removed</code> folder, never deleted).</p>%s</div>"
                   % files_table(share))
    if server or share:
        out.append(folded_inputs("how to set it up",
                                 "<p><a href=\"https://github.com/autobleem2/ext_store/blob/develop/server/"
                                 "INSTALL-linux.md\">Building it and running it as a service on Linux</a> "
                                 "&middot; <a href=\"https://github.com/autobleem2/ext_store/blob/develop/server/"
                                 "README.md\">every option</a></p>"))
    out = tabbed(out)
    out.append("<footer>Generated %s UTC &middot; theme: ab2.0.0</footer></main></body></html>"
               % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return "\n".join(out) + "\n"


def tabbed(out):
    """The page's platform sections - everything from each <h2 class="plat" id=...> to the next - as tabs:
    a tab bar after the intro panel, one <section class="tab"> per platform, a few lines of script that
    show the one named in the URL's #hash (the first otherwise) and keep the hash in step. Without script
    every section is shown in turn, headings and all, as before."""
    html_text = "\n".join(out)
    parts = re.split(r'<h2 class="plat" id="([a-z0-9]+)">([^<]+)</h2>', html_text)
    if len(parts) < 3:
        return out
    head, rest = parts[0], parts[1:]
    tabs = [(rest[i], rest[i + 1], rest[i + 2]) for i in range(0, len(rest), 3)]
    bar = "<nav class=\"tabs\" role=\"tablist\">" + "".join(
        "<a href=\"#%s\" data-tab=\"%s\" role=\"tab\">%s</a>" % (tid, tid, title) for tid, title, _ in tabs) + "</nav>"

    def subtabbed(parent, body):
        """a section with <h3 class="subtab" id=...> headings becomes a pill bar and one <section
        class="subtab"> per heading (the PC's two products); one without is returned as it is"""
        sub_parts = re.split(r'<h3 class="subtab" id="([a-z0-9-]+)">([^<]+)</h3>', body)
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
               "finishes the installation by itself. <a href=\"/repository/\">&larr; Downloads</a></p></div>")

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
               "<p>To update an installed Pi, download the Raspberry Pi tarball from the <a href=\"/repository/\">downloads</a> "
               "page, unpack it on the Pi and run <code>sudo bash install.sh</code> - it keeps the games partition "
               "and everything on it, and skips what is already installed.</p>"
               "<p>Questions and bug reports: <a href=\"https://github.com/autobleem/AutoBleem2\">github.com/autobleem/AutoBleem2</a>. "
               "The Pi's logs are in <code>System/Logs/</code> on the games partition.</p></div>")

    out.append("<footer>Generated %s UTC &middot; theme: ab2.0.0</footer></main></body></html>"
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
               "so an old PC works as well as a new one. <a href=\"/repository/\">&larr; Downloads</a></p>")
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


#*******************************
# the splash page (/) and the old addresses
#*******************************
def splash_nightly_row(nightly):
    """the splash's third row from index_nightly's builds: the newest one's day, "running"; none = "paused" """
    build = next((b for b in reversed(nightly or []) if b.get("files")), None) or (nightly[-1] if nightly else None)
    if not build:
        return ("Nightly builds", "every change, built overnight - none at the moment", "", "paused")
    return ("Nightly builds", "every change, built overnight - last one %s" % splash_day(build["date"]),
            "dev", "running")


def splash_day(date):
    day = datetime.strptime(date[:10], "%Y-%m-%d")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return "%d %s %d" % (day.day, months[day.month - 1], day.year)


def next_milestone(version):
    """v2.0.0-alpha1 -> alpha2, v2.0.0-rc2 -> rc3, v2.0.0-alpha1.1 -> alpha2 (a point release is a fix on its
    number, the milestone ahead is the next number); a stable or unreadable version -> None"""
    m = re.match(r"^v?\d+\.\d+(?:\.\d+)?-(alpha|beta|rc)(\d+)(?:\.\d+)?$", version)
    return "%s%d" % (m.group(1), int(m.group(2)) + 1) if m else None


def splash_release_rows(releases):
    """the splash's release rows from index_releases: the newest stable release (release channel), the
    pre-release when it is newer (testing channel) and the next milestone after it (amber, in progress)"""
    releases = sorted(releases or [], key=lambda r: version_key(r["version"]))
    stable = [r for r in releases if not r["prerelease"]]
    pre = [r for r in releases if r["prerelease"]]
    rows = []
    if stable:
        r = stable[-1]
        rows.append(("Latest release", "the release channel - %s" % splash_day(r["date"]), "rel", r["version"]))
    if pre and (not stable or version_key(pre[-1]["version"]) > version_key(stable[-1]["version"])):
        r = pre[-1]
        rows.append(("Latest pre-release", "the testing channel - %s" % splash_day(r["date"]), "pre", r["version"]))
        nxt = next_milestone(r["version"])
        if nxt:
            rows.append(("Next milestone", "in progress", "", nxt))
    if not rows:
        rows.append(("First pre-release", "in progress", "", "alpha1"))
    return rows


def render_splash(base_url, nightly=None, releases=None):
    """index.html: the splash - the logo, "AutoBleem 2 is coming", the status block (the release rows from
    `releases`, SPLASH_STATUS and the nightly row), the Download button (-> /repository/), a thank-you and the
    Ko-fi button (KOFI_URL, left out when empty)."""
    e = html.escape
    rows = []
    for label, note, cls, pill in splash_release_rows(releases) + list(SPLASH_STATUS) + [splash_nightly_row(nightly)]:
        rows.append("<li><span class=\"dot%s\"></span><span class=\"k\">%s<small>%s</small></span>"
                    "<span class=\"chan%s\">%s</span></li>"
                    % ("" if cls else " next", e(label), e(note), " " + cls if cls else "", e(pill)))
    support = ""
    if KOFI_URL:
        support = ("<a class=\"support\" href=\"%s\" target=\"_blank\" rel=\"noopener\" title=\"Support AutoBleem on Ko-fi\">"
                   "<img src=\"/assets/button-support.png\" srcset=\"/assets/button-support@2x.png 2x\" "
                   "alt=\"Support AutoBleem\"></a>" % e(KOFI_URL))
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>AutoBleem 2 is coming</title>\n"
            "<meta name=\"description\" content=\"AutoBleem 2 - the game launcher for the PlayStation Classic, the Raspberry Pi "
            "and the PC. Early builds are out.\">\n"
            "<meta property=\"og:title\" content=\"AutoBleem 2 is coming\"><meta property=\"og:image\" content=\"%s/assets/og.png\">\n"
            "%s\n<style>%s</style>\n"
            "</head><body class=\"splash\">\n"
            "<header class=\"top\"><div class=\"bar\"><a class=\"brand\" href=\"/\"><img src=\"/assets/emblem.png\" "
            "srcset=\"/assets/emblem@2x.png 2x\" alt=\"\">AutoBleem 2</a><nav>\n"
            "<a href=\"/repository/\">Downloads</a><a href=\"/store/\">Store</a><a href=\"/repository/#manuals\">Manual</a>"
            "%s<a href=\"https://github.com/autobleem2\">GitHub</a></nav></div></header>\n"
            "<main>\n"
            "  <img class=\"logo\" src=\"/assets/logo.png\" srcset=\"/assets/logo@2x.png 2x\" alt=\"AutoBleem 2\">\n"
            "  <h1>AutoBleem 2 is coming</h1>\n"
            "  <p class=\"sub\">The game launcher for the PlayStation Classic, the Raspberry Pi and the PC is being rebuilt from "
            "the ground up. It is not finished yet - but you can already try the early builds.</p>\n\n"
            "  <section class=\"status\" aria-label=\"Where we are\">\n    <h2>Where we are</h2>\n    <ul>\n      %s\n    </ul>\n"
            "  </section>\n\n"
            "  <a class=\"big\" href=\"/repository/\">Download early builds</a>\n\n"
            "  <p class=\"thanks\"><b>Thank you</b> to everyone downloading, testing and reporting - every early build that "
            "gets tried makes AutoBleem 2 better.</p>\n"
            "  %s\n"
            "  <p class=\"more\"><a href=\"/repository/\">All downloads</a> &middot; <a href=\"/store/\">AutoBleem Store</a> "
            "&middot; <a href=\"https://github.com/autobleem2\">Source on GitHub</a></p>\n"
            "</main>\n"
            "<footer><p>AutoBleem 2 is free and open source. PlayStation is a trademark of Sony Interactive Entertainment; "
            "AutoBleem is not affiliated with Sony.</p></footer>\n"
            "</body></html>\n" % (base_url, ICON_LINKS, PAGE_CSS, "<a href=\"/testing/\">Testing</a>" if HAS_TESTING else "",
               "\n      ".join(rows), support))


#*******************************
# the volunteer tester pages (testing/) and the test plans they are made from (testplans/)
#*******************************
# The plans arrive in testplans/<version>/<platform>.yaml (the hub's CI, repo_publish.sh testplans). The contract with
# the intake service and the admin panel is intake/README.md. No testplans/ folder = no pages and no error.
PLAN_PLATFORMS = ("psc", "rpi", "pcusb", "win")
PLAN_ID_RE = re.compile(r"^[a-z0-9]+$")


def _yaml_scalar(text):
    """One YAML scalar of the plan files' subset: a double or single quoted string, a number or a plain word."""
    text = text.strip()
    if text[:1] == "\"":
        i = 1
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "\"":
                break
            i += 1
        try:
            return json.loads(text[:i + 1])
        except ValueError:
            return text[1:i]
    if text[:1] == "'":
        out, i = [], 1
        while i < len(text):
            if text[i] == "'":
                if text[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(text[i])
            i += 1
        return "".join(out)
    text = re.sub(r"\s+#.*$", "", text)
    if text == "[]":
        return []
    if re.match(r"^-?\d+$", text):
        return int(text)
    return text


YAML_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$")


def _yaml_block(lines, i, indent):
    """The block that starts at lines[i] (all its lines at `indent`): a list or a map -> (value, next line)."""
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        items = []
        while i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
            rest = lines[i][1][1:]
            item = rest.strip()
            if not item:
                if i + 1 < len(lines) and lines[i + 1][0] > indent:
                    value, i = _yaml_block(lines, i + 1, lines[i + 1][0])
                else:
                    value, i = None, i + 1
            elif YAML_KEY_RE.match(item):
                sub = indent + 1 + (len(rest) - len(rest.lstrip()))
                lines[i] = (sub, item)
                value, i = _yaml_block(lines, i, sub)
            else:
                value, i = _yaml_scalar(item), i + 1
            items.append(value)
        return items, i
    mapping = {}
    while i < len(lines) and lines[i][0] == indent:
        m = YAML_KEY_RE.match(lines[i][1])
        if not m:
            raise ValueError("not a 'key: value' line: %s" % lines[i][1])
        key, rest = m.group(1), m.group(2)
        if rest is None or rest.strip() == "" or rest.strip().startswith("#"):
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if nxt and (nxt[0] > indent or (nxt[0] == indent and nxt[1].startswith("- "))):
                mapping[key], i = _yaml_block(lines, i + 1, nxt[0])
            else:
                mapping[key], i = None, i + 1
        else:
            mapping[key], i = _yaml_scalar(rest), i + 1
    return mapping, i


def parse_plan_yaml(text):
    """The subset of YAML the test plans use (maps, lists, quoted or plain scalars, # comment lines) - the server
    has only the standard library, so no PyYAML."""
    lines = [(len(raw) - len(raw.lstrip(" ")), raw.strip()) for raw in text.splitlines()
             if raw.strip() and not raw.lstrip().startswith("#")]
    if not lines:
        return {}
    value, _ = _yaml_block(lines, 0, lines[0][0])
    return value


def load_plan(path):
    """A plan file as the pages need it, or None (a warning on stderr) when it is not a usable plan."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = parse_plan_yaml(f.read())
        sections = []
        for s in raw["sections"]:
            steps = [{"id": str(st["id"]), "do": str(st["do"]), "expect": str(st.get("expect") or "")}
                     for st in s["steps"]]
            if not steps:
                raise ValueError("section %s has no steps" % s["id"])
            sections.append({"id": str(s["id"]), "title": str(s["title"]), "minutes": int(s.get("minutes") or 0),
                             "needs": str(s.get("needs") or ""), "steps": steps})
        if not sections:
            raise ValueError("no sections")
        before = raw.get("before_you_start") or []
        return {"id": str(raw["id"]), "title": str(raw["title"]), "version": str(raw.get("version") or ""),
                "before_you_start": [str(b) for b in before], "sections": sections}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print("testplans: %s skipped - %s: %s" % (path, type(e).__name__, e), file=sys.stderr)
        return None


def index_testplans(repo):
    """testplans/<version>/<platform>.yaml -> testplans/index.json (the contract: intake/README.md) and what the
    pages need: {"current", "versions", "plans": {platform: plan}, "pdf": {platform: url path}}; None without any
    plan. The current version is the highest folder by version_key."""
    global HAS_TESTING
    HAS_TESTING = False
    root = os.path.join(repo, "testplans")
    if not os.path.isdir(root):
        return None
    found = {}
    for version in os.listdir(root):
        folder = os.path.join(root, version)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            m = re.match(r"^([a-z0-9]+)\.yaml$", name)
            plan = load_plan(os.path.join(folder, name)) if m else None
            if plan:
                found.setdefault(version, {})[m.group(1)] = plan
    if not found:
        return None
    versions = sorted(found, key=version_key)
    current = versions[-1]
    order = [p for p in PLAN_PLATFORMS if p in found[current]] + sorted(p for p in found[current] if p not in PLAN_PLATFORMS)
    plans = {p: found[current][p] for p in order}
    write_json(os.path.join(root, "index.json"), {
        "current": current, "versions": versions[::-1],
        "platforms": {p: {"title": plan["title"], "sections": len(plan["sections"]),
                          "minutes": sum(s["minutes"] for s in plan["sections"])} for p, plan in plans.items()}})
    pdf = {p: "/testplans/%s/%s.pdf" % (current, p) for p in plans
           if os.path.isfile(os.path.join(root, current, p + ".pdf"))}
    HAS_TESTING = True
    print("testplans: %s, %d versions, platforms %s" % (current, len(versions), ", ".join(plans)))
    return {"current": current, "versions": versions[::-1], "plans": plans, "pdf": pdf}


TESTING_CSS = """
/* NEW - the Testing pages: forms, step rows, platform cards. Same tokens and cut corners as the approved look. */
header.top nav a.on{color:var(--cyan)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1rem;margin:1rem 0}
.grid .panel{margin:0;display:flex;flex-direction:column}
.grid .panel p{color:var(--dim);font-size:.92rem;flex:1}
.grid .panel h3{margin-top:0;color:#fff;font-size:1.05rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.two .panel{margin:1rem 0}
.cta{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;margin:1.2rem 0}
button.big,a.big.plain{display:inline-flex;align-items:center;gap:.7rem;padding:.8rem 1.8rem;font:inherit;font-size:1.05rem;
  font-weight:600;color:#fff;letter-spacing:.02em;border:0;cursor:pointer;position:relative;
  background:linear-gradient(180deg,#ff5cb6,#d9358f);--ring:rgba(255,255,255,.25);--cut:14px;
  clip-path:polygon(0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)))}
button.big:after{content:"";position:absolute;inset:0;pointer-events:none;background:var(--ring);
  clip-path:polygon(evenodd,0 0,calc(100% - var(--cut)) 0,100% var(--cut),100% 100%,var(--cut) 100%,0 calc(100% - var(--cut)),0 0,
    1px 1px,calc(100% - 1px - var(--cut) + .59px) 1px,calc(100% - 1px) calc(1px + var(--cut) - .59px),calc(100% - 1px) calc(100% - 1px),
    calc(1px + var(--cut) - .59px) calc(100% - 1px),1px calc(100% - 1px - var(--cut) + .59px),1px 1px)}
button.big:hover,a.big.plain:hover{background:linear-gradient(180deg,#ff73c1,#e8409c);text-decoration:none}
a.big.plain:before{content:none}
a.dl.wide{margin-top:.4rem;align-self:flex-start}
a.dl.quiet{--ring:var(--line-soft);color:var(--steel);background:rgba(18,22,28,.6)}
label.f{display:block;margin:1rem 0 .3rem;font-weight:600;color:var(--steel);font-size:.9rem}
label.f small{font-weight:500;color:var(--dim);margin-left:.4rem}
input[type=text],input[type=email],select,textarea,input[type=file]{width:100%;font:inherit;font-size:.95rem;color:var(--ink);
  background:rgba(18,22,28,.78);border:1px solid var(--line);border-radius:0;padding:.5rem .65rem}
textarea{min-height:5.5rem;resize:vertical}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--magenta)}
input::placeholder,textarea::placeholder{color:#6f7d8b}
.hint{color:var(--dim);font-size:.85rem;margin:.25rem 0 0}
.row2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1rem}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}
.check{display:flex;gap:.6rem;align-items:flex-start;margin:.8rem 0;color:var(--ink);font-size:.92rem}
.check input{margin-top:.25rem;accent-color:var(--magenta)}
.privacy{color:var(--dim);font-size:.85rem;border-left:3px solid var(--cyan);padding:.1rem 0 .1rem .8rem;margin:1rem 0}
.sec{display:flex;flex-wrap:wrap;align-items:baseline;gap:.8rem;margin:1.8rem 0 .2rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
.sec h2{margin:0;color:#fff;font-size:1.1rem;text-transform:none;letter-spacing:.02em}
.sec small{color:var(--dim)}
.step{padding:.8rem 0;border-bottom:1px solid var(--line-soft)}
.step:last-child{border-bottom:0}
.step .top{display:flex;gap:.8rem;align-items:flex-start}
.step .sid{flex:none;font-family:ui-monospace,Consolas,monospace;font-size:.78rem;color:var(--dim);background:rgba(0,0,0,.28);
  padding:.1rem .4rem;margin-top:.15rem}
.step .txt{flex:1;min-width:0}
.step .txt b{font-weight:600;color:#fff}
.step .txt small{display:block;color:var(--dim);font-size:.85rem;margin-top:.15rem}
.choice{display:flex;gap:.4rem;margin:.55rem 0 0 0;flex-wrap:wrap}
.choice label{cursor:pointer}
.choice input{position:absolute;opacity:0;pointer-events:none}
.choice span{display:inline-block;padding:.2rem .9rem;font-size:.86rem;font-weight:600;color:var(--steel);
  background:rgba(18,22,28,.6);border:1px solid var(--line-soft)}
.choice input:focus-visible+span{border-color:var(--magenta)}
.choice input:checked+span.ok{color:var(--rel);border-color:var(--rel);background:rgba(88,224,160,.1)}
.choice input:checked+span.pr{color:var(--warn);border-color:var(--warn);background:rgba(255,138,101,.12)}
.choice input:checked+span.na{color:#fff;border-color:var(--dim);background:rgba(154,168,182,.14)}
.cmt{display:none;margin-top:.5rem}
.step:has(input[value=problem]:checked) .cmt{display:block}
.cmt textarea{min-height:3.4rem}
.progress{position:sticky;top:3.3rem;z-index:3;background:rgba(18,22,28,.92);border-bottom:1px solid var(--line-soft);
  padding:.4rem 0;margin:0 0 .4rem;display:flex;align-items:center;gap:.8rem;font-size:.85rem;color:var(--dim)}
.progress .bar{flex:1;height:4px;background:var(--line-soft);position:relative}
.progress .bar i{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,var(--cyan),var(--magenta))}
.idrow{display:flex;gap:1rem;align-items:center}
.idrow input{max-width:15rem;font-family:ui-monospace,Consolas,monospace;font-size:1.2rem;letter-spacing:.15em}
.stat{margin:.2rem 0 1rem}
ol.stages{list-style:none;margin:0 0 1rem;padding:0 0 0 .4rem}
ol.stages li{position:relative;margin:0;padding:.2rem 0 1rem 1.6rem;border-left:2px solid var(--line-soft)}
ol.stages li:last-child{padding-bottom:.2rem}
ol.stages li:before{content:"";position:absolute;left:-7px;top:.45rem;width:12px;height:12px;border-radius:50%;background:var(--bg);border:2px solid var(--dim)}
ol.stages li.done:before{background:var(--rel);border-color:var(--rel)}
ol.stages li.now:before{background:var(--magenta);border-color:var(--magenta);box-shadow:0 0 8px var(--magenta)}
ol.stages li b{color:#fff;font-weight:600}
ol.stages li small{display:block;color:var(--dim);font-size:.85rem}
.sub{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;margin:1.2rem 0}
.idbox{display:inline-block;font-family:ui-monospace,Consolas,monospace;font-size:1.8rem;letter-spacing:.2em;color:#fff;
  background:rgba(0,0,0,.35);border:1px solid var(--line);padding:.4rem 1.1rem;margin:.4rem 0}
ol.next li{margin:.5rem 0}ol.next b{color:#fff;font-weight:600}
@media (max-width:640px){
  .two,.row2{grid-template-columns:minmax(0,1fr)}
  .step .top{flex-direction:column;gap:.3rem}
  .progress{top:2.9rem}
  .idbox{font-size:1.3rem;letter-spacing:.12em}
  header.top nav a.xs{display:none}
}

.err{color:var(--warn);margin:.6rem 0}
.step.bad{border-left:3px solid var(--warn);padding-left:.6rem}
.step.prob .cmt{display:block}
.hidden{display:none}
"""

TESTING_PRIVACY = ("What you send is stored on the project's server, read only by the project's maintainers, and used "
                   "to fix problems and plan the next release. Contact details are optional and used only to ask "
                   "about your report. Logs are kept only to investigate the report.")

# the small script every Testing page shares: el() builds a node with text only (never innerHTML - the plan's
# texts are data, not markup), api() posts JSON and turns an {"error": ...} answer into an exception
TESTING_JS = """
function $(id){return document.getElementById(id)}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function readJson(r){return r.json().catch(function(){return {}}).then(function(j){
  if(!r.ok||j.error)throw new Error(j.error||('The server answered '+r.status));return j})}
function api(path,body){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body)}).then(readJson)}
function qs(name){var m=location.search.match(new RegExp('[?&]'+name+'=([^&]*)'));
  try{return m?decodeURIComponent(m[1]):''}catch(e){return ''}}
"""

TASK_JS = """
(function(){
var D=JSON.parse($('plan-data').textContent),P=D.platform,V=D.version,KEY='abtp:'+P+':'+V,S={};
function load(){try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return {}}}
function save(){try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}}
function forget(){try{localStorage.removeItem(KEY)}catch(e){}}
function showError(msg,retry){var box=$('task');box.textContent='';box.appendChild(el('p','err',msg));
  if(retry){var b=el('button','copy','Try again');b.type='button';b.onclick=start;box.appendChild(b)}}
function start(){
  S=load();$('task').textContent='Looking for a task for you...';
  var body={platform:P,version:V};if(S.claim)body.claim=S.claim;
  api('/submit/claim',body).then(function(c){
    if(S.claim!==c.claim){var keep=S.section===c.section.id&&S.answers;
      S={claim:c.claim,answers:keep?S.answers:{},device:S.device||'',contact:S.contact||''}}
    S.section=c.section.id;S.expires=c.expires||'';save();render()
  }).catch(function(e){showError('Could not get a task: '+e.message,true)})}
function stamp(d){function z(n){return(n<10?'0':'')+n}
  return d.getDate()+' '+['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]+' '+
    d.getFullYear()+', '+z(d.getHours())+':'+z(d.getMinutes())}
function section(){for(var i=0;i<D.sections.length;i++)if(D.sections[i].id===S.section)return D.sections[i];return null}
function counts(sec){var n=0;sec.steps.forEach(function(st){if(S.answers[st.id]&&S.answers[st.id].status)n++});return n}
function progress(sec){var n=counts(sec),t=sec.steps.length;
  $('pcount').textContent=n+' of '+t+' answered';$('pbar').style.width=Math.round(100*n/t)+'%'}
function render(){
  var sec=section(),box=$('task');
  if(!sec){forget();showError('This task is not in the plan any more.',true);return}
  box.textContent='';
  var note=el('div','notice'),label=el('span','label');
  label.appendChild(el('b',null,'Task claimed for you'));
  var when=S.expires?new Date(S.expires):null;
  label.appendChild(document.createTextNode(' - '+D.title+', '+sec.title+(sec.minutes?' (about '+sec.minutes+' min)':'')+
    (when&&!isNaN(when)?'. Send it by '+stamp(when)+' or it goes back to the pool.':'.')));
  note.appendChild(label);box.appendChild(note);
  var form=el('form');form.noValidate=true;
  var panel=el('div','panel'),row=el('div','row2'),a=el('div'),b=el('div');
  var la=el('label','f','Your device ');la.appendChild(el('small',null,'optional'));a.appendChild(la);
  var dev=el('input');dev.type='text';dev.maxLength=200;dev.placeholder='e.g. PlayStation Classic, EU model, 8 GB stick';
  dev.value=S.device||'';dev.oninput=function(){S.device=dev.value;save()};a.appendChild(dev);
  var lb=el('label','f','Contact ');lb.appendChild(el('small',null,'optional - only used to ask about your answers'));b.appendChild(lb);
  var ct=el('input');ct.type='email';ct.maxLength=200;ct.placeholder='e-mail';ct.value=S.contact||'';
  ct.oninput=function(){S.contact=ct.value;save()};b.appendChild(ct);
  row.appendChild(a);row.appendChild(b);panel.appendChild(row);
  var hp=el('div','hp'),hl=el('label',null,'Leave this empty '),hi=el('input');hi.type='text';hi.name='website';hi.tabIndex=-1;
  hi.autocomplete='off';hl.appendChild(hi);hp.appendChild(hl);panel.appendChild(hp);form.appendChild(panel);
  var pr=el('div','progress');pr.appendChild(el('span')).id='pcount';
  var bar=el('span','bar');bar.appendChild(el('i')).id='pbar';pr.appendChild(bar);
  pr.appendChild(el('span',null,sec.minutes?'about '+sec.minutes+' min':''));form.appendChild(pr);
  var head=el('div','sec');head.appendChild(el('h2',null,sec.title));
  if(sec.needs)head.appendChild(el('small',null,'You need: '+sec.needs));form.appendChild(head);
  sec.steps.forEach(function(st){
    var cur=S.answers[st.id]||{},d=el('div','step');d.id='s-'+st.id;
    var top=el('div','top');top.appendChild(el('span','sid',st.id));
    var txt=el('div','txt');txt.appendChild(el('b',null,st.do));
    if(st.expect)txt.appendChild(el('small',null,'You should see: '+st.expect));
    var ch=el('div','choice'),cmt=el('div','cmt'),ta=el('textarea');ta.maxLength=2000;
    ta.placeholder='What happened instead? (a few words are enough)';ta.value=cur.comment||'';
    function mark(){d.classList.toggle('prob',(S.answers[st.id]||{}).status==='problem')}
    [['ok','ok','OK'],['problem','pr','Problem'],['na','na','Not applicable']].forEach(function(o){
      var l=el('label'),r=el('input');r.type='radio';r.name=st.id;r.value=o[0];r.checked=cur.status===o[0];
      r.onchange=function(){var x=S.answers[st.id]||(S.answers[st.id]={});x.status=o[0];d.classList.remove('bad');
        mark();save();progress(sec)};
      l.appendChild(r);l.appendChild(el('span',o[1],o[2]));ch.appendChild(l)});
    ta.oninput=function(){var x=S.answers[st.id]||(S.answers[st.id]={});x.comment=ta.value;d.classList.remove('bad');save()};
    cmt.appendChild(ta);txt.appendChild(ch);txt.appendChild(cmt);top.appendChild(txt);d.appendChild(top);
    form.appendChild(d);mark()});
  form.appendChild(el('p','privacy',D.privacy));
  var err=el('p','err hidden');form.appendChild(err);
  var sub=el('div','sub'),send=el('button','big','Send my results');send.type='submit';
  var back=el('a','dl quiet','Give it back');back.href='#';sub.appendChild(send);sub.appendChild(back);
  form.appendChild(sub);box.appendChild(form);progress(sec);
  function fail(msg){err.textContent=msg;err.classList.remove('hidden')}
  back.onclick=function(ev){ev.preventDefault();if(back.dataset.busy)return;back.dataset.busy='1';
    api('/submit/claim',{platform:P,version:V,claim:S.claim,release:true}).catch(function(){}).then(function(){
      forget();location.href='/testing/'})};
  form.onsubmit=function(ev){ev.preventDefault();err.classList.add('hidden');
    var steps=[],bad=null;
    sec.steps.forEach(function(st){var x=S.answers[st.id]||{},d=$('s-'+st.id);
      var comment=(x.comment||'').trim();
      if(!x.status||(x.status==='problem'&&!comment)){d.classList.add('bad');if(!bad)bad=d}
      steps.push({id:st.id,status:x.status||'',comment:x.status==='problem'?comment:''})});
    if(bad){fail('Please answer every step - use Not applicable for one you could not try - and say what happened on each Problem.');
      bad.scrollIntoView({block:'center'});return}
    send.disabled=true;
    api('/submit/testplan',{platform:P,version:V,section:S.section,claim:S.claim,steps:steps,
      device:(S.device||'').trim(),contact:(S.contact||'').trim(),website:hi.value}).then(function(r){
      forget();location.href='/testing/thanks.html?id='+encodeURIComponent(r.id)+'&p='+encodeURIComponent(P)+'&k=result'
    }).catch(function(e){send.disabled=false;fail('Could not send: '+e.message)})}
}
start();
})();
"""

COVERAGE_JS = """
(function(){
var g=$('cards');
fetch('/submit/coverage?version='+encodeURIComponent(g.dataset.version)).then(function(r){return r.ok?r.json():null})
.then(function(j){if(!j||!j.platforms)return;
  Array.prototype.forEach.call(document.querySelectorAll('.cov'),function(e){
    var c=j.platforms[e.dataset.p];if(!c||!c.section)return;
    e.textContent='Most needed now: ';e.appendChild(el('b',null,c.section.title));
    e.lastChild.style.color='var(--ink)';
    e.appendChild(document.createTextNode(' - '+c.passes+(j.target?' of '+j.target:'')+' done'))})
}).catch(function(){})})();
"""

REPORT_JS = """
(function(){
var f=$('f'),pl=$('pl'),v=$('v'),vo=$('vo'),lg=$('lg'),err=$('err');
v.onchange=function(){vo.classList.toggle('hidden',v.value!=='')};
function fail(m){err.textContent=m;err.classList.remove('hidden')}
f.onsubmit=function(ev){ev.preventDefault();err.classList.add('hidden');
  var ver=v.value||vo.value.trim(),file=lg.files&&lg.files[0];
  if(!pl.value)return fail('Please pick your device.');
  if(!ver)return fail('Please give the version, or write "not sure".');
  if(!$('st').value.trim()&&!$('ac').value.trim())return fail('Please tell us what you did or what happened.');
  if(file){
    if(!/\\.zip$/i.test(file.name))return fail('The log file must be a .zip.');
    if(file.size>25*1024*1024)return fail('The log file is larger than 25 MB.');
    if(!$('cb').checked)return fail('Tick the box to agree to send the logs, or remove the file.')}
  var fd=new FormData();fd.append('platform',pl.value);fd.append('version',ver);fd.append('steps',$('st').value);
  fd.append('expected',$('ex').value);fd.append('actual',$('ac').value);fd.append('contact',$('ct').value.trim());
  fd.append('website',$('hp').value);
  if(file){fd.append('logs',file);fd.append('consent_logs','on')}
  var send=$('send');send.disabled=true;
  fetch('/submit/issue',{method:'POST',body:fd}).then(readJson).then(function(r){
    location.href='/testing/thanks.html?id='+encodeURIComponent(r.id)
  }).catch(function(e){send.disabled=false;fail('Could not send: '+e.message)})}
})();
"""

THANKS_JS = """
(function(){
var id=qs('id'),p=qs('p');
if(qs('k')==='result'){document.querySelector('.hero p').textContent='Thank you - we have your test result.';
  $('keep').textContent='Keep this id. It is the only way to look your result up - there is no mailbox.'}
if(/^[a-z0-9]{1,16}$/.test(id)){$('rid').textContent=id;$('st').href='/testing/status.html?id='+id}
else{$('rid').classList.add('hidden');$('st').classList.add('hidden')}
if(/^[a-z0-9]+$/.test(p))$('again').href='/testing/'+p+'.html';
})();
"""

STATUS_JS = """
(function(){
var LABELS={'received':['Received','','We have it and will read it. New reports are sorted once a day.'],
 'needs-info':['Needs more info','pre','Send a new report and put this id in the first line of "What did you do?".'],
 'to-reproduce':['We are trying to repeat it','','Only a problem we can repeat on the newest build becomes a bug.'],
 'not-a-bug':['Not a bug','','We looked at it and it is not something to fix.'],
 'idea':['Idea - kept for the next plan','dev','It is on the "User ideas" list and read when we plan the next release.']};
function show(j){var out=$('out');out.textContent='';out.classList.remove('hidden');
  var h=el('h2',null,j.id);h.appendChild(el('small',null,(j.kind==='testplan'?'test result':'problem report')+
    (j.received?' - sent '+String(j.received).slice(0,10):'')));out.appendChild(h);
  var st=String(j.state||''),m=/^bug (BUG-\\d+)$/.exec(st),l=m?['Recorded as '+m[1],'rel',
    'It is on the list of things to fix. The next alpha will say if it is fixed.']:(LABELS[st]||[st,'','']);
  var p=el('p','stat');p.appendChild(el('span','chan '+l[1],l[0]));out.appendChild(p);
  if(l[2])out.appendChild(el('p','older',l[2]))}
function look(id){var out=$('out'),err=$('err');err.classList.add('hidden');out.classList.add('hidden');
  if(!/^[a-z0-9]{8}$/.test(id)){err.textContent='A report id is 8 letters and digits.';err.classList.remove('hidden');return}
  fetch('/submit/status/'+id).then(readJson).then(show).catch(function(e){
    err.textContent=e.message;err.classList.remove('hidden')})}
$('f').onsubmit=function(ev){ev.preventDefault();look($('rid').value.trim().toLowerCase())};
var q=qs('id');if(q){$('rid').value=q;look(q.toLowerCase())}
})();
"""


def testing_page(title, tagline, body, script=""):
    """A Testing page: the site's shared head and CSS plus the Testing pieces, the page's body, its script."""
    return (page_head(title, tagline, TESTING_CSS) + "<main>" + body + "</main><footer>AutoBleem 2</footer>"
            "<script>" + TESTING_JS + script + "</script></body></html>\n")


def script_json(data):
    """JSON for a <script type="application/json"> block: nothing in it can close the tag or start a comment."""
    return (json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_testing_index(info):
    e = html.escape
    cards = []
    for p, plan in info["plans"].items():
        minutes = sum(s["minutes"] for s in plan["sections"])
        pdf = ("<p class=\"older\" style=\"margin:.7rem 0 0;font-size:.82rem\"><a href=\"%s\">Printable "
               "version</a></p>" % e(info["pdf"][p]) if p in info["pdf"] else "")
        cards.append("<div class=\"panel\"><h3>%s</h3><p>%d sections in all, about %d minutes.</p>"
                     "<p class=\"older cov\" data-p=\"%s\"></p><a class=\"dl wide\" href=\"/testing/%s.html\">"
                     "Give me a task (~10 min)</a>%s</div>" % (e(plan["title"]), len(plan["sections"]), minutes, e(p), e(p), pdf))
    body = (
        "<p class=\"lede\"><b>Alpha testing</b> means trying an early build before everyone gets it, and telling us "
        "what works and what does not. Anyone with one of the supported devices can join as a volunteer - no "
        "experience needed, no login. You do not test everything: pick your device and we hand you <b>one small "
        "task of about ten minutes</b>, the part that needs testing most. Take another one when you like.</p>"
        "<div class=\"cta\"><a class=\"dl\" href=\"/repository/\">Go to the downloads</a><span class=\"older\">Pick your "
        "device below - the plan's first lines say what to download. Testing %s.</span></div>"
        "<h2 class=\"plat\" style=\"margin-top:1.6rem\">Pick your device</h2>"
        "<div class=\"grid\" id=\"cards\" data-version=\"%s\">%s</div>"
        "<p class=\"older\">Your task is kept for you in this browser for a while; if you do not send it by then it goes "
        "back to the pool.</p>"
        "<div class=\"panel\"><h2>Something went wrong?</h2><p>Tell us even if you are not following a plan. It takes "
        "about five minutes, and a log file from the console helps a lot.</p><div class=\"cta\" style=\"margin:.6rem 0 0\">"
        "<a class=\"big plain\" href=\"/testing/report.html\">Report a problem</a></div></div>"
        "<div class=\"two\"><div class=\"panel\"><h2>What happens to your report</h2><p>Each report gets an id. We read "
        "it, try to repeat it on the newest build, and only then call it a bug and fix it.</p><p><b>A bug</b> is "
        "something that should work and does not. <b>An idea</b> is something you would like it to do - ideas are "
        "welcome, they are kept on a \"User ideas\" list and read when we plan the next release.</p>"
        "<p>You can look up your report by its id on the <a href=\"/testing/status.html\">status page</a>.</p></div>"
        "<div class=\"panel\"><h2>Your data</h2><p class=\"older\">%s</p></div></div>"
        % (e(info["current"]), e(info["current"]), "".join(cards), e(TESTING_PRIVACY)))
    return testing_page("Testing - AutoBleem 2", "Help us test the alpha - on your own hardware.", body, COVERAGE_JS)


def render_testing_task(info, platform):
    e = html.escape
    plan = info["plans"][platform]
    data = {"platform": platform, "version": info["current"], "title": plan["title"], "privacy": TESTING_PRIVACY,
            "sections": plan["sections"]}
    before = ""
    if plan["before_you_start"]:
        before = ("<details class=\"inputs\"><summary><b>Before you start</b> what you need for this plan</summary>"
                  "<div><ul>%s</ul></div></details>" % "".join("<li>%s</li>" % e(b) for b in plan["before_you_start"]))
    pdf = ("<p class=\"older\">The whole plan for this device is also a <a href=\"%s\">printable PDF</a>.</p>"
           % e(info["pdf"][platform]) if platform in info["pdf"] else "")
    body = ("<p class=\"lede\"><a href=\"/testing/\">&larr; Testing</a> &nbsp; This is <b>one small task</b>, about ten "
            "minutes. Answer each step - use Not applicable for one you could not try - and send it at the end. Your "
            "answers stay in this browser if you close the page.</p>%s"
            "<noscript><p class=\"err\">This page needs JavaScript to hand you a task.</p></noscript>"
            "<div id=\"task\"></div>%s<script type=\"application/json\" id=\"plan-data\">%s</script>"
            % (before, pdf, script_json(data)))
    return testing_page("%s - testing - AutoBleem 2" % plan["title"], "Your task - %s." % plan["title"], body, TASK_JS)


def render_testing_report(info):
    e = html.escape
    platforms = "".join("<option value=\"%s\">%s</option>" % (e(p), e(plan["title"])) for p, plan in info["plans"].items())
    versions = "".join("<option value=\"%s\">%s</option>" % (e(v), e(v)) for v in info["versions"])
    body = (
        "<p class=\"lede\"><a href=\"/testing/\">&larr; Testing</a> &nbsp; Tell us what happened, in your own words. "
        "<b>Ideas are welcome too</b> - write them here as well; they are kept on a \"User ideas\" list and read when "
        "we plan the next release.</p>"
        "<form id=\"f\" action=\"/submit/issue\" method=\"post\" enctype=\"multipart/form-data\" class=\"panel\" novalidate>"
        "<div class=\"row2\"><div><label class=\"f\" for=\"pl\" style=\"margin-top:0\">Device</label>"
        "<select id=\"pl\" name=\"platform\">%s</select></div>"
        "<div><label class=\"f\" for=\"v\" style=\"margin-top:0\">Version</label>"
        "<select id=\"v\" name=\"version\">%s<option value=\"\">Other / not sure</option></select>"
        "<input type=\"text\" id=\"vo\" class=\"hidden\" maxlength=\"100\" placeholder=\"the version, or not sure\" "
        "style=\"margin-top:.4rem\"><p class=\"hint\">Options, then About, shows it.</p></div></div>"
        "<label class=\"f\" for=\"st\">What did you do? <small>step by step</small></label>"
        "<textarea id=\"st\" name=\"steps\" maxlength=\"5000\" placeholder=\"1. Options, then Updates&#10;2. Chose nightly&#10;"
        "3. Waited a minute\"></textarea>"
        "<label class=\"f\" for=\"ex\">What did you expect to happen?</label><textarea id=\"ex\" name=\"expected\" "
        "maxlength=\"5000\" style=\"min-height:3.6rem\"></textarea>"
        "<label class=\"f\" for=\"ac\">What happened instead?</label><textarea id=\"ac\" name=\"actual\" maxlength=\"5000\" "
        "style=\"min-height:3.6rem\"></textarea>"
        "<label class=\"f\" for=\"lg\">Log files <small>optional - a .zip, up to 25 MB</small></label>"
        "<input type=\"file\" id=\"lg\" name=\"logs\" accept=\".zip\">"
        "<p class=\"hint\">On the console: Hardware Information, then \"Save logs\" writes a folder to the stick. Zip that "
        "folder.</p>"
        "<label class=\"check\"><input type=\"checkbox\" id=\"cb\" name=\"consent_logs\"><span>I agree to send these logs. "
        "I know they can contain my Wi-Fi name, game names and device ids. <b>Required when a file is attached.</b>"
        "</span></label>"
        "<label class=\"f\" for=\"ct\">Contact <small>optional - only used to ask about this report</small></label>"
        "<input type=\"email\" id=\"ct\" name=\"contact\" maxlength=\"200\" placeholder=\"e-mail\">"
        "<div class=\"hp\"><label>Leave this empty <input type=\"text\" id=\"hp\" name=\"website\" tabindex=\"-1\" "
        "autocomplete=\"off\"></label></div>"
        "<p class=\"privacy\">%s</p><p class=\"err hidden\" id=\"err\"></p>"
        "<div class=\"sub\" style=\"margin-bottom:0\"><button class=\"big\" id=\"send\" type=\"submit\">Send the report"
        "</button><span class=\"older\">You get a report id to look it up later.</span></div></form>"
        "<noscript><p class=\"err\">Sending needs JavaScript.</p></noscript>" % (platforms, versions, e(TESTING_PRIVACY)))
    return testing_page("Report a problem - AutoBleem 2", "Report a problem.", body, REPORT_JS)


def render_testing_thanks():
    body = ("<div class=\"panel\" style=\"margin-top:1.4rem\"><h1>Received - thank you</h1><p id=\"keep\">Keep this id. It is the "
            "only way to look your report up - there is no mailbox.</p><div class=\"idbox\" id=\"rid\"></div>"
            "<h3>What happens next</h3><ol class=\"next\"><li><b>We read it.</b> New reports are sorted once a day.</li>"
            "<li><b>We try to repeat it</b> on the newest development build. Only a problem we can repeat becomes a "
            "bug.</li><li><b>An idea</b> goes on the \"User ideas\" list and is read when we plan the next release.</li>"
            "<li><b>The status</b> changes to \"received\", \"needs more info\", \"recorded as BUG-N\" or \"not a bug\"."
            "</li></ol><div class=\"cta\" style=\"margin-bottom:0\"><a class=\"big plain\" id=\"again\" "
            "href=\"/testing/\">Take another task</a><a class=\"dl\" id=\"st\" href=\"/testing/status.html\">See the "
            "status of this id</a><a class=\"dl quiet\" href=\"/testing/\">Back to Testing</a></div></div>")
    return testing_page("Thank you - AutoBleem 2", "Thank you - we have your report.", body, THANKS_JS)


def render_testing_status():
    body = ("<p class=\"lede\"><a href=\"/testing/\">&larr; Testing</a> &nbsp; Enter the id you were given after sending "
            "a report. Nothing else is shown - no names, no contact details.</p>"
            "<form id=\"f\" class=\"panel\"><label class=\"f\" for=\"rid\" style=\"margin-top:0\">Report id</label>"
            "<div class=\"idrow\"><input type=\"text\" id=\"rid\" name=\"id\" maxlength=\"8\" autocomplete=\"off\">"
            "<button class=\"big\" type=\"submit\">Look it up</button></div><p class=\"err hidden\" id=\"err\"></p></form>"
            "<div class=\"panel hidden\" id=\"out\"></div>")
    return testing_page("Report status - AutoBleem 2", "Look up a report by its id.", body, STATUS_JS)


def testing_pages(info):
    """[(path under the repository, page)] for the Testing pages of the current version's plans"""
    pages = [(os.path.join("testing", "index.html"), render_testing_index(info)),
             (os.path.join("testing", "report.html"), render_testing_report(info)),
             (os.path.join("testing", "thanks.html"), render_testing_thanks()),
             (os.path.join("testing", "status.html"), render_testing_status())]
    for platform in info["plans"]:
        if PLAN_ID_RE.match(platform) and platform not in ("index", "report", "thanks", "status"):
            pages.append((os.path.join("testing", platform + ".html"), render_testing_task(info, platform)))
    return pages


def render_moved(name):
    """a page that moved to /repository/<name>: the old address stays alive for old links, a refresh and a link"""
    target = "/repository/" + name
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Moved</title><meta http-equiv=\"refresh\" content=\"0; url=%s\">"
            "<link rel=\"canonical\" href=\"%s\"></head><body>"
            "<p>This page has moved to <a href=\"%s\">%s</a>.</p></body></html>\n" % (target, target, target, target))


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

    testplans = index_testplans(repo)  # first: it decides whether every page's bar links Testing
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
    preview = index_nightly(repo, base_url, "preview")
    write_channels(repo)
    store_pages = {}
    store = index_store(repo, base_url, store_pages)
    extensions = index_extensions(repo, base_url)
    pcsx = {name: index_pcsx(repo, base_url, name) for name, _, _ in EMULATORS}
    pcsx = {name: b for name, b in pcsx.items() if b}
    pc = {"builds": pc_builds, "cores": pc_cores, "images": pc_images, "win": win}
    os.makedirs(os.path.join(repo, "repository"), exist_ok=True)
    pages = [("index.html", render_splash(base_url, nightly, releases)),
             (os.path.join("repository", "index.html"),
              render_index(base_url, releases, builds, cores, images, dbs, psc_builds, psc_cores, samples,
                           psc_libs, psc_apps, psc_bios, pc, pcsx, manuals, psc_kernel, nightly, store_pages,
                           preview)),
             (os.path.join("repository", "rpi-install.html"), render_rpi_install(base_url, images)),
             (os.path.join("repository", "pc-install.html"), render_pc_install(base_url, pc_images)),
             ("rpi-install.html", render_moved("rpi-install.html")),
             ("pc-install.html", render_moved("pc-install.html"))]
    if os.path.isdir(os.path.join(repo, "store")) or extensions.get("store") or extensions.get("lanshare"):
        os.makedirs(os.path.join(repo, "store"), exist_ok=True)
        pages.append((os.path.join("store", "index.html"),
                      render_store(base_url, store_pages, extensions.get("store"), extensions.get("lanshare"))))
    if testplans:
        os.makedirs(os.path.join(repo, "testing"), exist_ok=True)
        pages.extend(testing_pages(testplans))
    for name, page in pages:
        tmp = os.path.join(repo, os.path.dirname(name), ".%s.tmp" % os.path.basename(name))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(tmp, os.path.join(repo, name))
    if store:
        print("store: " + ", ".join("%s %d items" % (p, n) for p, n in store.items()))
    for name, entry in extensions.items():
        print("extension %s: %s" % (name, ", ".join("%s %s" % (c, b["version"]) for c, b in entry.items())))
    print("%s: %d releases, %d RetroArch builds, %d cores tarballs, %d PSC RetroArch builds, %s PSC cores, %d image sets, "
          "%d PC RetroArch builds, %d PC cores tarballs, %d PC image sets, %d databases, %s sample pack, %d manuals" % (
        repo, len(releases), len(builds), len(cores), len(psc_builds), "1" if psc_cores else "0", len(images),
        len(pc_builds), len(pc_cores), len(pc_images), len(dbs), "1" if samples else "0", len(manuals)))


if __name__ == "__main__":
    main()
