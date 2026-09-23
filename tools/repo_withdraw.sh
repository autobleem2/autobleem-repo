#!/usr/bin/env bash
# repo_withdraw.sh - take a bad testing or nightly build off the download site, reversibly.
#
#   REPO_DIR=<site tree> tools/repo_withdraw.sh nightly  v2.0.0-alpha2-25-g7a37132
#   REPO_DIR=<site tree> tools/repo_withdraw.sh testing  v2.0.0-alpha3
#   REPO_DIR=<site tree> tools/repo_withdraw.sh restore  <kind> <version>      puts one back
#
# The build's folders are moved, never deleted, into <site>/.withdrawn/<kind>/<version>/ (Caddy hides dot
# folders): a nightly's nightly/<version>/; a testing build's releases/<version>/ and its image sets
# (rpi-imager/images/<version>/, pc/images/<version>/). Then the caller regenerates the catalogs and the page
# (`tools/repo_publish.sh --local index`) - the channel falls back to what is left, as the launcher's update
# check and the installers do. A stable release is never withdrawn this way.
set -euo pipefail
REPO_DIR="${REPO_DIR:?REPO_DIR is the site tree}"
usage() { sed -n '2,6p' "$0" >&2; exit 2; }

restore=0
if [ "${1:-}" = restore ]; then restore=1; shift; fi
kind="${1:-}"; version="${2:-}"
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] || usage
case "$kind" in
    nightly) folders=("nightly/$version") ;;
    testing)
        [[ "$version" == *-* ]] || { echo "$version is a stable release - not withdrawn this way" >&2; exit 1; }
        folders=("releases/$version" "rpi-imager/images/$version" "pc/images/$version") ;;
    *) usage ;;
esac

store="$REPO_DIR/.withdrawn/$kind/$version"
moved=0
for f in "${folders[@]}"; do
    if [ "$restore" = 1 ]; then
        src="$store/$f" dst="$REPO_DIR/$f"
    else
        src="$REPO_DIR/$f" dst="$store/$f"
    fi
    [ -d "$src" ] || continue
    [ -e "$dst" ] && { echo "$dst exists already - nothing moved" >&2; exit 1; }
    mkdir -p "$(dirname "$dst")"
    mv "$src" "$dst"
    echo "$([ "$restore" = 1 ] && echo restored || echo withdrew) $f"
    moved=$((moved + 1))
done
[ "$moved" -gt 0 ] || { echo "no $kind build $version on the site" >&2; exit 1; }
if [ "$restore" = 1 ]; then
    find "$REPO_DIR/.withdrawn" -depth -type d -empty -delete 2>/dev/null || true
fi
