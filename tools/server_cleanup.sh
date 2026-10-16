#!/bin/bash
# The build server's routine cleanup (the disk ran full on 2026-09-23 and took the runner down with it):
#   - dangling images, containers stopped for more than a day, build cache unused for three days,
#   - every image older than three days that no container uses (docker rmi refuses the ones a
#     container - running or not - still uses, so a running build and the runner itself are safe); no image of
#     a KEEP_IMAGES repository (autobleem-build, autobleem-kernel-build; all tags, whatever the age) is ever
#     in that list.
# A failing `docker images` listing fails the script (exit 1, message on stderr).
# DRY_RUN=1 (or --dry-run) prints what would be removed and removes nothing.
# Docker refuses to remove an image a container still uses, so a running build is never touched. The site's
# old nightlies are not this script's: repo_index.py prunes them on every publish (NIGHTLY_KEEP).
# The site's tree is not this script's at all - and source/ (the GPL source archives of the PE Apps, kept at least
# 3 years after an item's last release) and deps/ (the mirrored build dependencies) must never be added to anything
# that deletes: tests/test_pe_site.py fails if the cleanup ever names them.
# Needs the Docker socket - .github/workflows/cleanup.yml runs it on the self-hosted runner every night.
#
#   tools/server_cleanup.sh [--dry-run]
#   tools/server_cleanup.sh --check-disk    only the alarm below, no cleanup
#
# The alarm (AUTOBLEEM-20): the repo has no notification channel (no webhook, no mail), so a disk above
# DISK_WARN_PCT (default 90) % used is reported the one way the runner can: the step fails with an ::error::
# annotation on the run, which GitHub mails to whoever watches the workflow. cleanup.yml runs it as its last
# step, after the docker cleanup and the index run (which prunes the old nightlies), so it fires only when
# those did not make room.
set -uo pipefail

check_disk() {
    local limit=${DISK_WARN_PCT:-90} used
    used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
    echo "disk: / is ${used:-?}% used (limit $limit%)"
    if [ -n "$used" ] && [ "$used" -gt "$limit" ]; then
        echo "::error title=Build server disk almost full::/ is ${used}% used (limit ${limit}%) - free space before the next build dies"
        return 1
    fi
}

if [ "${1:-}" = --check-disk ]; then
    check_disk
    exit $?
fi

DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
[ "${DRY_RUN:-0}" = 1 ] && DRY=1
# Repositories whose images (every tag) are never removed; an entry matches the whole repository or its last
# path component. docker/run.sh needs the kernel-build image locally.
KEEP_IMAGES=${KEEP_IMAGES:-"autobleem-build ghcr.io/autobleem2/autobleem-build autobleem-kernel-build"}

run() {
    [ "$DRY" = 1 ] && echo "would run:"
    echo "+ $*"
    [ "$DRY" = 1 ] || "$@"
}

echo "== before"
df -h / | tail -1
docker system df

echo "== dangling images, stopped containers"
run docker image prune -f
run docker container prune -f --filter until=24h
# 2026-10-02: a blanket `docker image prune -a` removed the 72 h old :develop build image (no container used it)
# and the server, not logged in to ghcr, could not pull it back - every self-hosted publish step then failed with
# "denied". So the old unused images are removed one by one, and no image of a KEEP_IMAGES repository (any tag)
# is ever listed (rmi, unlike prune, never touches an image a container uses).
# docker 24 has no `until` filter on `docker images` (only on prune), so the age is checked here from CreatedAt.
echo "== unused old images"
if ! listing=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}'); then
    echo "::error title=Image cleanup failed::'docker images' failed - no image was removed" >&2
    echo "server_cleanup: cannot list docker images" >&2
    exit 1
fi
cutoff=$(date -d '72 hours ago' +%s)
while read -r ref id day time zone _; do
    [ -n "$ref" ] || continue
    repo=${ref%:*}
    keep=0
    for k in $KEEP_IMAGES; do
        { [ "$repo" = "$k" ] || [ "${repo##*/}" = "${k##*/}" ]; } && keep=1
    done
    [ "$keep" = 0 ] || continue
    created=$(date -d "$day $time $zone" +%s 2>/dev/null) || continue
    [ "$created" -lt "$cutoff" ] || continue
    case "$ref" in *:\<none\>) ref=$id ;; esac
    run docker rmi "$ref" || echo "   (in use - kept)"
done <<< "$listing"
echo "== stale build cache"
run docker builder prune -f --filter until=72h

echo "== after"
df -h / | tail -1
docker system df
