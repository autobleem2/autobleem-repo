#!/bin/bash
# The build server's routine cleanup (the disk ran full on 2026-09-23 and took the runner down with it):
#   - every ghcr.io/autobleem2/autobleem-build tag but :develop and :latest (each image build leaves a :<sha>
#     tag; the tags share most layers, but together they held ~5 GB),
#   - dangling images, containers stopped for more than a day, build cache unused for three days.
# Docker refuses to remove an image a container still uses, so a running build is never touched. The site's
# old nightlies are not this script's: repo_index.py prunes them on every publish (NIGHTLY_KEEP).
# Needs the Docker socket - .github/workflows/cleanup.yml runs it on the self-hosted runner every night.
#
#   tools/server_cleanup.sh [--dry-run]
set -uo pipefail

DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
KEEP_TAGS="develop latest"
BUILD_IMAGE=ghcr.io/autobleem2/autobleem-build

run() {
    echo "+ $*"
    [ "$DRY" = 1 ] || "$@"
}

echo "== before"
df -h / | tail -1
docker system df

echo "== old build image tags"
docker images "$BUILD_IMAGE" --format '{{.Tag}}' | while read -r tag; do
    case " $KEEP_TAGS " in *" $tag "*) continue ;; esac
    run docker rmi "$BUILD_IMAGE:$tag" || echo "   (in use - kept)"
done

echo "== dangling images, stopped containers, stale build cache"
run docker image prune -f
run docker container prune -f --filter until=24h
run docker builder prune -f --filter until=72h

echo "== after"
df -h / | tail -1
docker system df
