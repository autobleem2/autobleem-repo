#!/usr/bin/env bash
# Publish files to the download repository (CLAUDE.md, "The download repository") and regenerate its index.
#
#   tools/repo_publish.sh release v2.0.0 dist/psc/*.zip dist/rpi/*.tar.gz ...   -> releases/v2.0.0/
#   tools/repo_publish.sh nightly v2.0.0-alpha2-14-gabc1234 dist/*/*.tar.gz dist/*/*.img.xz ...
#                                                                              -> nightly/<version>/ (a development build of
#                                                                                 develop: the release packages and images; the
#                                                                                 3 newest kept, never an update channel)
#   tools/repo_publish.sh preview preview-feature-ab-gui-1a2b3c dist/*/*.tar.gz ...
#                                                                              -> preview/<version>/ (a build of a feature
#                                                                                 branch, PLATFORM-20: like a nightly, the
#                                                                                 newest kept; --partial too)
#   tools/repo_publish.sh image v2.0.0-pre0-933bd2f build_rpi_image/*.img.xz build_rpi_image/rpi_imager_repo.json
#                                                                              -> rpi-imager/images/<version>/
#   tools/repo_publish.sh retroarch v1.22.2 retroarch-v1.22.2-armhf.tar.gz     -> rpi/retroarch/v1.22.2/
#   tools/repo_publish.sh cores armhf build_cores/dist/cores-armhf-*.tar.gz    -> rpi/cores/armhf/
#   tools/repo_publish.sh pc-image v2.0.0-pre0-933bd2f build_pc_image/out/*.img.xz  -> pc/images/<version>/ (the PC stick)
#   tools/repo_publish.sh pc-retroarch v1.22.2 retroarch-v1.22.2-i386.tar.gz    -> pc/retroarch/v1.22.2/
#   tools/repo_publish.sh pc-cores i386 build_cores/dist/cores-i386-*.tar.gz    -> pc/cores/i386/
#   tools/repo_publish.sh psc-retroarch v1.22.2-1 dist/release/retroarch-psc-v1.22.2-1.zip dist/release/manifest.json
#                                                                              -> psc/retroarch/v1.22.2-1/ (the retroarch-psc repo's `make publish`)
#   tools/repo_publish.sh psc-cores dist/release/cores-psc-20260920.tar.gz dist/release/cores-psc-20260920.json
#                                                                              -> psc/cores/ (newest date kept)
#   tools/repo_publish.sh psc-libs dist/release/libs-psc-20260920.tar.gz dist/release/libs-psc-20260920.json
#                                                                              -> psc/libs/ (newest date kept)
#   tools/repo_publish.sh psc-apps dist/release/apps-psc-20260920.tar.gz dist/release/apps-psc-20260920.json
#                                                                              -> psc/apps/ (newest date kept; tools/pack_psc_apps.py)
#   tools/repo_publish.sh win-retroarch 1.22.2 build_retroarch/dist/retroarch-win64-1.22.2.tar.gz -> win/retroarch/1.22.2/
#   tools/repo_publish.sh win-cores build_cores/dist/cores-win64-20260920.tar.gz    -> win/cores/ (the Windows product's
#                                                                                      RetroArch, cores and BIOS list -
#                                                                                      AutoBleemWinSetup reads them)
#   tools/repo_publish.sh win-bios src/win/biospack-win64.txt                       -> win/bios/
#   tools/repo_publish.sh store psc opentyrian-psc-2.1.zip opentyrian.item.json opentyrian.png
#                                                                              -> store/psc/ (the AutoBleem Store's catalog)
#   tools/repo_publish.sh extension store 1.0.0 dist/ext_store-*.zip dist/abstored-*  -> extensions/store/<version>/ (an
#                                                                                 extension's own packages, from its CI;
#                                                                                 newest release + a newer dev build kept)
#   tools/repo_publish.sh psc-bios payload/RetroArch/bios/biospack.txt          -> psc/bios/ (the BIOS list the installer
#                                                                                 fetches RetroBIOS's files by; the list only)
#   tools/repo_publish.sh samples build_samples/samples-20260920.tar.gz build_samples/samples-20260920.json
#                                                                              -> samples/ (newest date kept)
#   tools/repo_publish.sh pcsx v2.0.0 ../pcsx-abnxt/dist/packages/*             -> emu/pcsx-abnxt/<version>/ (a v* tag build:
#                                                                                 release, or testing for a pre-release tag -
#                                                                                 repo_index.py's index_pcsx tells them apart
#                                                                                 by the version string; newest per channel kept)
#   tools/repo_publish.sh pcsx-ab v2.0.0 ../pcsx-ab2/dist/packages/*            -> emu/pcsx-ab/<version>/ (the same; pcsx-ab is
#                                                                                 no longer developed - a tag release only, no
#                                                                                 nightly kind for it)
#   tools/repo_publish.sh pcsx-nightly r26-20-gb9801962 ../pcsx-abnxt/dist/packages/*
#                                                                              -> emu/pcsx-abnxt/nightly/<version>/ (a develop-push
#                                                                                 build - the nightly channel; newest kept, an older one pruned)
#   tools/repo_publish.sh manuals build_manuals/*/*.pdf                        -> manuals/ (the user manuals, one PDF
#                                                                                 per language - tools/build_manuals.py)
#   tools/repo_publish.sh testplans testing/alpha1/*.yaml testing/alpha1/*.pdf -> testplans/<version>/ (the volunteer test
#                                                                                 plans, from the hub's CI: each file goes
#                                                                                 into the folder named by its own
#                                                                                 `version:` line; the index then writes
#                                                                                 testplans/index.json and the testing/ pages)
#   tools/repo_publish.sh db db/covers*.db                                     -> db/
#   tools/repo_publish.sh mirror opentyrian tyrian21.zip                       -> mirror/opentyrian/ (third-party files a
#                                                                                 build fetches - an App's freeware game
#                                                                                 data - kept as they are, never indexed)
#   tools/repo_publish.sh assets                                               -> assets/ (tools/repo_assets.py stages
#                                                                                 tools/site-assets/: the page's picture,
#                                                                                 logo, emblem, icon, font)
#   tools/repo_publish.sh index                                                just regenerate the index
#   tools/repo_publish.sh withdraw <kind> <version> [--dry-run] [--local]      removes a published version's
#                                                                                 folder (release/nightly/image/
#                                                                                 retroarch/cores/pc-image/
#                                                                                 pc-retroarch/pc-cores/
#                                                                                 psc-retroarch/win-retroarch/
#                                                                                 pcsx/pcsx-ab/pcsx-nightly, or
#                                                                                 "extension <name> <version>", or
#                                                                                 "version <v>": all of a version)
#                                                                                 and re-indexes: the newest
#                                                                                 *remaining* version is then
#                                                                                 what latest.json/release.json/
#                                                                                 unstable.json/os_list*.json
#                                                                                 list, not necessarily the one
#                                                                                 withdrawn. --dry-run prints
#                                                                                 the exact folder and the files
#                                                                                 in it and touches nothing (its
#                                                                                 ssh calls are read-only listings).
#   tools/repo_publish.sh --partial nightly <version> FILES...                 part of a development build that is still
#                                                                                 being published (each image as it is
#                                                                                 built, then the packages): the files go
#                                                                                 into nightly/<version>/ with a
#                                                                                 .incomplete marker and the index is NOT
#                                                                                 run - repo_index.py leaves a marked
#                                                                                 folder out, so the previous nightly
#                                                                                 stays whole. The run's last publish,
#                                                                                 a plain `nightly <version> ...`, takes
#                                                                                 the marker away and indexes.
#
# The page generator travels with every publish, three-way merged with the repository's copy (see
# tools/repo_index_merge.py) - never copied over it.
#
# The files go over ssh (rsync to $REPO_HOST, "psc-build" in ~/.ssh/config, into $REPO_DIR) with a .sha256
# next to each; then tools/repo_index.py runs on the server over the whole tree (it is uploaded as
# <repo>/.tools/repo_index.py so the server needs no checkout). --local skips ssh and copies within this
# machine - what a CI job on the server does, with $REPO_DIR bind-mounted.
#
# AB_REPO_URL is what the generated urls start with (default: the domain; http://212.71.244.78:9090 is the
# same tree without TLS). Retention is the index script's: a pre-release replaces the previous pre-release
# (releases and image sets), only the newest RetroArch build (Pi and PSC alike) and cores tarball are kept, stable
# releases stay.
set -euo pipefail

REPO_HOST="${REPO_HOST:-psc-build}"
REPO_DIR="${REPO_DIR:-/home/claude/autobleem-repo}"
AB_REPO_URL="${AB_REPO_URL:-https://autobleem.retromenele.pl}"
LOCAL=0
PARTIAL=0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# the Python that runs this machine's own steps (the generator merge, the assets): $PYTHON, else python3 or python
# on PATH, else - an MSYS2 login shell on Windows drops the Windows PATH - the user's Python under %LOCALAPPDATA%
# (the Microsoft Store one or a python.org install). The server's steps always run its own python3.
find_python() {
    if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
    local p base
    for p in python3 python; do
        if command -v "$p" >/dev/null 2>&1; then command -v "$p"; return; fi
    done
    # %LOCALAPPDATA% (a login shell may not pass it on: cygpath's folder id 28 is the same folder)
    base="$( { [ -n "${LOCALAPPDATA:-}" ] && cygpath -u "$LOCALAPPDATA"; } 2>/dev/null || cygpath -u -F 28 2>/dev/null || true)"
    if [ -n "$base" ]; then
        for p in "$base"/Microsoft/WindowsApps/python3.exe "$base"/Programs/Python/Python3*/python.exe; do
            if [ -x "$p" ]; then echo "$p"; return; fi
        done
    fi
    echo "repo_publish.sh: no python3 or python found - set PYTHON=<path to python>" >&2
    return 1
}
PY="$(find_python)"

# The upload needs rsync and an ssh that works with it. Git Bash on Windows has no rsync (and its own ssh does not
# match MSYS2's rsync), so there ssh and rsync run from MSYS2's bin dir - for those two calls only (MSYS2's mktemp,
# python and tar would hand the rest of the script paths Windows programs cannot read). Without any rsync the publish
# stops here, non-zero and with a message, before anything is staged or sent (it used to run on into "rsync: command
# not found").
MSYS_TOOLS=""
use_transport() {
    [ "$LOCAL" -eq 1 ] && return 0
    local m="${MSYS2_BIN:-/c/msys64/usr/bin}"
    if ! command -v rsync >/dev/null 2>&1; then
        if [ -x "$m/rsync.exe" ] || [ -x "$m/rsync" ]; then
            MSYS_TOOLS="$m"
        else
            echo "repo_publish.sh: no rsync on PATH - install rsync (Windows: MSYS2's, $m/rsync.exe). Nothing was published." >&2
            exit 1
        fi
    fi
    command -v ssh >/dev/null 2>&1 || [ -n "$MSYS_TOOLS" ] || { echo "repo_publish.sh: no ssh on PATH. Nothing was published." >&2; exit 1; }
}
ssh() { if [ -n "$MSYS_TOOLS" ]; then PATH="$MSYS_TOOLS:$PATH" command ssh "$@"; else command ssh "$@"; fi; }
upload() { # upload STAGE-DIR
    local src="$1" rc=0
    if [ -n "$MSYS_TOOLS" ]; then
        # /c/Users/... - MSYS2's rsync reads "C:/..." as a host name, and Git Bash's own /tmp is not MSYS2's /tmp
        # (cygpath -u keeps "/tmp/..." there), so the drive form is built from the Windows path
        local w
        w="$(cygpath -m "$1")"
        src="/$(printf '%s' "${w:0:1}" | tr 'A-Z' 'a-z')${w:2}"
        PATH="$MSYS_TOOLS:$PATH" command rsync -rlt --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r "$src"/ "$REPO_HOST:$REPO_DIR/" || rc=$?
    else
        rsync -rlt --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r "$src"/ "$REPO_HOST:$REPO_DIR/" || rc=$?
    fi
    [ "$rc" -eq 0 ] || { echo "repo_publish.sh: the upload to $REPO_HOST:$REPO_DIR failed (rsync exit $rc). Nothing was published." >&2; exit 1; }
}

usage() { sed -n '2,92p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

withdraw_usage() {
    cat <<'EOF' >&2
Usage: tools/repo_publish.sh withdraw <kind> <version> [--dry-run] [--local]
       tools/repo_publish.sh withdraw extension <name> <version> [--dry-run] [--local]

Removes a published version's folder and re-indexes, so the newest remaining version is
what latest.json / release.json / unstable.json / os_list*.json list next - not
necessarily the version just withdrawn (repo_index.py's index_* functions read the tree
with os.listdir(), so once the folder is gone the next-newest wins on its own).

<kind> is one of: release, nightly, preview, image, retroarch, cores, pc-image, pc-retroarch,
pc-cores, psc-retroarch, win-retroarch, pcsx, pcsx-ab, pcsx-nightly, extension - or `version`: every folder of
that version (and of the development builds counted from it) in every versioned tree, for a withdrawn release.

--dry-run prints the exact folder and its files, and the re-index command that would run,
then exits without touching anything - its ssh call is a read-only listing only.
--local acts on $REPO_DIR on this machine instead of over ssh to $REPO_HOST (what a CI
job does with $REPO_DIR bind-mounted; --dry-run still only lists, never removes).
EOF
    exit "${1:-0}"
}

do_withdraw() {
    shift # "withdraw"
    [ $# -ge 1 ] || withdraw_usage 1
    local wkind="$1"; shift
    local dry=0 wlocal=0 pos1="" pos2=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run) dry=1; shift ;;
            --local) wlocal=1; shift ;;
            -h|--help) withdraw_usage 0 ;;
            *) if [ -z "$pos1" ]; then pos1="$1"; else pos2="$1"; fi; shift ;;
        esac
    done
    local wdest=""
    case "$wkind" in
        release)       [ -n "$pos1" ] || withdraw_usage 1; wdest="releases/$pos1" ;;
        nightly)       [ -n "$pos1" ] || withdraw_usage 1; wdest="nightly/$pos1" ;;
        preview)       [ -n "$pos1" ] || withdraw_usage 1; wdest="preview/$pos1" ;;
        image)         [ -n "$pos1" ] || withdraw_usage 1; wdest="rpi-imager/images/$pos1" ;;
        retroarch)     [ -n "$pos1" ] || withdraw_usage 1; wdest="rpi/retroarch/$pos1" ;;
        cores)         [ -n "$pos1" ] || withdraw_usage 1; wdest="rpi/cores/$pos1" ;;
        pc-image)      [ -n "$pos1" ] || withdraw_usage 1; wdest="pc/images/$pos1" ;;
        pc-retroarch)  [ -n "$pos1" ] || withdraw_usage 1; wdest="pc/retroarch/$pos1" ;;
        pc-cores)      [ -n "$pos1" ] || withdraw_usage 1; wdest="pc/cores/$pos1" ;;
        psc-retroarch) [ -n "$pos1" ] || withdraw_usage 1; wdest="psc/retroarch/$pos1" ;;
        win-retroarch) [ -n "$pos1" ] || withdraw_usage 1; wdest="win/retroarch/$pos1" ;;
        pcsx)          [ -n "$pos1" ] || withdraw_usage 1; wdest="emu/pcsx-abnxt/$pos1" ;;
        pcsx-ab)       [ -n "$pos1" ] || withdraw_usage 1; wdest="emu/pcsx-ab/$pos1" ;;
        pcsx-nightly)      [ -n "$pos1" ] || withdraw_usage 1; wdest="emu/pcsx-abnxt/nightly/$pos1" ;;
        extension)     [ -n "$pos1" ] && [ -n "$pos2" ] || withdraw_usage 1; wdest="extensions/$pos1/$pos2" ;;
        # a whole version, everywhere (2026-10-03: the withdrawn v2.0.0-alpha2's images and emulator builds were left
        # behind by a release-only withdraw, and the index then pruned the new alpha1 as "older"): every folder named
        # <version> or <version>-<n>-g<hash>... (a development build counted from it) under the versioned trees
        version)       [ -n "$pos1" ] || withdraw_usage 1; wdest="" ;;
        *) echo "unknown withdraw kind: $wkind" >&2; withdraw_usage 1 ;;
    esac

    local listing index_cmd wdests run
    index_cmd="cd '$REPO_DIR' && python3 .tools/repo_index.py . --base-url '$AB_REPO_URL'"
    if [ "$wlocal" -eq 1 ]; then run() { bash -c "$1"; }; else run() { ssh "$REPO_HOST" "$1"; }; fi
    if [ "$wkind" = version ]; then
        wdests="$(run "cd '$REPO_DIR' && find releases rpi-imager/images pc/images emu nightly preview -mindepth 1 -maxdepth 3 \
            -type d \\( -name '$pos1' -o -name '$pos1-[0-9]*' \\) -prune -print 2>/dev/null | sort || true")"
    else
        wdests="$(run "[ -d '$REPO_DIR/$wdest' ] && echo '$wdest' || true")"
    fi
    if [ -z "$wdests" ]; then
        echo "nothing to withdraw: no ${wdest:-folder of $pos1} in $REPO_DIR ($( [ "$wlocal" -eq 1 ] && echo "on this machine" || echo "on $REPO_HOST"))" >&2
        exit 1
    fi
    echo "withdraw: kind=$wkind"
    while IFS= read -r d; do
        listing="$(run "find '$REPO_DIR/$d' -maxdepth 1 -mindepth 1 -printf '%f\\n' | sort" </dev/null)"  # ssh would eat the loop's input
        echo "will remove $REPO_DIR/$d/ and its files:"
        echo "$listing" | sed 's/^/  /'
    done <<<"$wdests"
    echo "will then re-run: python3 .tools/repo_index.py . --base-url $AB_REPO_URL (in $REPO_DIR$( [ "$wlocal" -eq 1 ] && echo " on this machine" || echo " on $REPO_HOST"))"
    if [ "$dry" -eq 1 ]; then
        echo "--dry-run: nothing removed, nothing re-indexed"
        exit 0
    fi
    run "set -e; cd '$REPO_DIR'; $(while IFS= read -r d; do printf "rm -rf '%s'; " "$d"; done <<<"$wdests") $index_cmd"
    echo "withdrawn and re-indexed: $(tr '\n' ' ' <<<"$wdests")"
}

if [ "${1:-}" = withdraw ]; then
    do_withdraw "$@"
    exit $?
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --local) LOCAL=1; shift ;;
        --partial) PARTIAL=1; shift ;;
        -h|--help) usage ;;
        *) break ;;
    esac
done
[ $# -ge 1 ] || usage 1
KIND="$1"; shift

# where the files of this kind land, relative to the repository root
case "$KIND" in
    release)   [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="releases/$VERSION" ;;
    nightly)   [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="nightly/$VERSION" ;;
    preview)   [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="preview/$VERSION" ;;
    image)     [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="rpi-imager/images/$VERSION" ;;
    retroarch) [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="rpi/retroarch/$VERSION" ;;
    cores)     [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="rpi/cores/$VERSION" ;;
    pc-image)  [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="pc/images/$VERSION" ;;
    pc-retroarch) [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="pc/retroarch/$VERSION" ;;
    pc-cores)  [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="pc/cores/$VERSION" ;;
    psc-retroarch) [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="psc/retroarch/$VERSION" ;;
    psc-cores) [ $# -ge 1 ] || usage 1; DEST="psc/cores" ;;
    psc-libs)  [ $# -ge 1 ] || usage 1; DEST="psc/libs" ;;
    psc-kernel) [ $# -ge 1 ] || usage 1; DEST="psc/kernel" ;;
    psc-apps)  [ $# -ge 1 ] || usage 1; DEST="psc/apps" ;;
    psc-bios)  [ $# -ge 1 ] || usage 1; DEST="psc/bios" ;;
    store)     [ $# -ge 2 ] || usage 1; PLATFORM="$1"; shift; DEST="store/$PLATFORM" ;;
    extension) [ $# -ge 3 ] || usage 1; NAME="$1"; VERSION="$2"; shift 2; DEST="extensions/$NAME/$VERSION" ;;
    win-retroarch) [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="win/retroarch/$VERSION" ;;
    win-cores) [ $# -ge 1 ] || usage 1; DEST="win/cores" ;;
    win-bios)  [ $# -ge 1 ] || usage 1; DEST="win/bios" ;;
    samples)   [ $# -ge 1 ] || usage 1; DEST="samples" ;;
    pcsx)      [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="emu/pcsx-abnxt/$VERSION" ;;
    pcsx-ab)   [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="emu/pcsx-ab/$VERSION" ;;
    pcsx-nightly)    [ $# -ge 2 ] || usage 1; VERSION="$1"; shift; DEST="emu/pcsx-abnxt/nightly/$VERSION" ;;
    manuals)   [ $# -ge 1 ] || usage 1; DEST="manuals" ;;
    testplans) [ $# -ge 1 ] || usage 1; DEST="testplans" ;;
    db)        [ $# -ge 1 ] || usage 1; DEST="db" ;;
    mirror)    [ $# -ge 2 ] || usage 1; NAME="$1"; shift; DEST="mirror/$NAME" ;;
    assets)    DEST="assets" ;;
    index)     DEST="" ;;
    *)         echo "unknown kind: $KIND" >&2; usage 1 ;;
esac
if [ "$PARTIAL" -eq 1 ] && [ "$KIND" != nightly ] && [ "$KIND" != preview ]; then
    echo "--partial is for a development build (nightly, preview) only" >&2
    exit 1
fi
use_transport

# a scratch dir with the files to upload and their sidecars, so one rsync does it
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$STAGE.assets"' EXIT

if [ "$KIND" = assets ]; then
    # repo_assets.py stages tools/site-assets/ (checked in); a theme directory as $2 is accepted and ignored
    "$PY" "$HERE/repo_assets.py" "$STAGE.assets" ${2:+"$2"}
    set -- "$STAGE.assets"/*
fi

# a test plan goes into the folder its own `version:` line names (the hub's folder is only a short name like
# alpha1); the file must be <platform>.yaml and the version a plain folder name
plan_version() {
    local v
    case "$(basename "$1")" in
        *[!a-z0-9.]*|.*|*.*.*) echo "not a test plan (<platform>.yaml): $1" >&2; return 1 ;;
        *.yaml) ;;
        *) echo "not a test plan (<platform>.yaml): $1" >&2; return 1 ;;
    esac
    v="$(sed -n 's/^version:[[:space:]]*//p' "$1" | head -n 1 | tr -d "\"'\r")"
    case "$v" in
        ""|*[!A-Za-z0-9._-]*|.*) echo "no usable 'version:' line in $1" >&2; return 1 ;;
    esac
    echo "$v"
}

if [ -n "$DEST" ]; then
    mkdir -p "$STAGE/$DEST"
    for f in "$@"; do
        [ -f "$f" ] || { echo "not a file: $f" >&2; exit 1; }
        FDEST="$DEST"
        if [ "$KIND" = testplans ]; then
            plan="$f"
            case "$f" in
                # a plan's printable PDF goes beside its yaml: the one passed in this call with the same name
                *.pdf) plan="${f%.pdf}.yaml"
                       case " $* " in *" $plan "*) ;; *) echo "no $(basename "$plan") in this call for $f" >&2; exit 1 ;; esac ;;
            esac
            pv="$(plan_version "$plan")" || exit 1
            FDEST="$DEST/$pv"
        fi
        mkdir -p "$STAGE/$FDEST"
        cp "$f" "$STAGE/$FDEST/"
        case "$f" in
            *.json|*.txt|*.sha256|*.ttf|*.yaml) ;;
            *) (cd "$STAGE/$FDEST" && sha256sum "$(basename "$f")" > "$(basename "$f").sha256") ;;
        esac
    done
    if [ "$KIND" = testplans ]; then
        echo "publishing to $DEST: $(cd "$STAGE/$DEST" && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ')"
    else
        echo "publishing to $DEST: $(cd "$STAGE/$DEST" && ls | grep -v '\.sha256$' | tr '\n' ' ')"
    fi
fi

# part of a development build: the files and the marker, no generator, no index (see --partial above)
if [ "$PARTIAL" -eq 1 ]; then
    touch "$STAGE/$DEST/.incomplete"
    if [ "$LOCAL" -eq 1 ]; then
        mkdir -p "$REPO_DIR"
        cp -r "$STAGE"/. "$REPO_DIR"/
        if [ "$(id -u)" -eq 0 ]; then chown -R "$(stat -c %u:%g "$REPO_DIR")" "$REPO_DIR"; fi
    else
        upload "$STAGE"
    fi
    echo "staged (not indexed until the build's last publish): $AB_REPO_URL/$DEST/"
    exit 0
fi
# the index script travels with every publish, merged three-way with the copy the repository runs
# (tools/repo_index_merge.py): two checkouts publishing in turn no longer overwrite each other's page
# generator, and a real conflict stops the publish before anything is copied
mkdir -p "$STAGE/.tools" "$STAGE/.merge"
if [ "$LOCAL" -eq 1 ]; then
    for f in repo_index.py repo_index.base.py repo_index.rev; do
        [ -f "$REPO_DIR/.tools/$f" ] && cp "$REPO_DIR/.tools/$f" "$STAGE/.merge/$f"
    done
else
    ssh "$REPO_HOST" "cd $REPO_DIR/.tools 2>/dev/null && tar cf - repo_index.py repo_index.base.py repo_index.rev 2>/dev/null || true"         | tar xf - -C "$STAGE/.merge" 2>/dev/null || true
fi
if ! "$PY" "$HERE/repo_index_merge.py" --mine "$HERE/repo_index.py"         --theirs "$STAGE/.merge/repo_index.py" --theirs-base "$STAGE/.merge/repo_index.base.py"         --theirs-rev "$STAGE/.merge/repo_index.rev"         --out "$STAGE/.tools/repo_index.py" --out-base "$STAGE/.tools/repo_index.base.py"         --out-rev "$STAGE/.tools/repo_index.rev"; then
    KEEP="$(mktemp -d "${TMPDIR:-/tmp}/repo_index_conflict.XXXXXX")"
    cp "$STAGE/.tools/repo_index.py" "$KEEP/repo_index.py" 2>/dev/null || true
    cp "$STAGE/.merge/repo_index.py" "$KEEP/repo_index.repository.py" 2>/dev/null || true
    echo "not published: the merged copy with the conflict markers is $KEEP/repo_index.py (the repository's own copy next to it)" >&2
    exit 1
fi
rm -rf "$STAGE/.merge"

# the index run on the server (and the image retention)
remote_index() {
    cat <<EOF
set -e
cd "$REPO_DIR"
$( { [ "$KIND" = nightly ] || [ "$KIND" = preview ]; } && echo "rm -f \"$DEST/.incomplete\" # the build's last publish: it is whole now" )
if [ -f assets/icon.png ]; then mkdir -p rpi-imager && cp assets/icon.png rpi-imager/icon.png; fi
if [ -f assets/favicon.ico ]; then cp assets/favicon.ico favicon.ico; fi
if ! python3 .tools/repo_index.py . --base-url "$AB_REPO_URL"; then
    if [ -f .tools/repo_index.prev.py ]; then
        # the base and its revision go back with the copy: left at the new version, the next publish's merge
        # took the new generator for already applied and kept the old one (2026-09-23)
        echo "the merged repo_index.py failed - the previous copy (and its merge base) is restored and run" >&2
        cp .tools/repo_index.prev.py .tools/repo_index.py
        for f in base.py rev; do
            [ -f .tools/repo_index.prev.\$f ] && cp .tools/repo_index.prev.\$f .tools/repo_index.\$f
        done
        python3 .tools/repo_index.py . --base-url "$AB_REPO_URL"
    fi
    exit 1
fi
cp .tools/repo_index.py .tools/repo_index.prev.py
for f in base.py rev; do
    [ -f .tools/repo_index.\$f ] && cp .tools/repo_index.\$f .tools/repo_index.prev.\$f
done
EOF
}

if [ "$LOCAL" -eq 1 ]; then
    mkdir -p "$REPO_DIR"
    cp -r "$STAGE"/. "$REPO_DIR"/
    rc=0
    bash -c "$(remote_index)" || rc=$?
    # a CI job publishes as root in a container: hand the tree back to its owner, or the next publish from a
    # checkout (as that user) cannot rewrite the release.json / SHA256SUMS / index.html root left behind
    # (2026-09-23: the appliance's first alpha publish did exactly that)
    if [ "$(id -u)" -eq 0 ]; then chown -R "$(stat -c %u:%g "$REPO_DIR")" "$REPO_DIR"; fi
    [ "$rc" -eq 0 ] || exit "$rc"
else
    upload "$STAGE"
    ssh "$REPO_HOST" "$(remote_index)"         || { echo "repo_publish.sh: the files are on $REPO_HOST but the index run there failed (exit $?)." >&2; exit 1; }
fi
echo "done: $AB_REPO_URL/${DEST:+$DEST/}"
