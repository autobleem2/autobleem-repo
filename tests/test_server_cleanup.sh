#!/bin/bash
# tools/server_cleanup.sh against a fake `docker` on PATH: old unused images are removed, young and in-use
# ones kept, no image of a KEEP_IMAGES repository is ever removed, a failing listing fails the script, and a
# dry run removes nothing.   Run: bash tests/test_server_cleanup.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT=$HERE/../tools/server_cleanup.sh
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/bin"

cat > "$WORK/bin/docker" <<'EOF'
#!/bin/bash
# fake docker: FAKE_DIR/images = the listing, FAKE_DIR/log = every removal, FAKE_DIR/inuse = refs rmi refuses
case "$1" in
images)
    [ -e "$FAKE_DIR/fail" ] && { echo "Cannot connect to the Docker daemon" >&2; exit 1; }
    cat "$FAKE_DIR/images" ;;
rmi)
    if grep -qxF "$2" "$FAKE_DIR/inuse"; then echo "conflict: image is in use" >&2; exit 1; fi
    echo "rmi $2" >> "$FAKE_DIR/log" ;;
image|container|builder) echo "$*" >> "$FAKE_DIR/other" ;;
esac
exit 0
EOF
chmod +x "$WORK/bin/docker"

OLD=$(date -d '10 days ago' '+%Y-%m-%d %H:%M:%S +0000 UTC')
YOUNG=$(date -d '1 hour ago' '+%Y-%m-%d %H:%M:%S +0000 UTC')
FAILS=0

setup() {
    export FAKE_DIR=$WORK/fake
    rm -rf "$FAKE_DIR"; mkdir "$FAKE_DIR"
    : > "$FAKE_DIR/log"; : > "$FAKE_DIR/inuse"
    cat > "$FAKE_DIR/images" <<EOT
example/old-tool:1.0 aaa111 $OLD
example/young-tool:2.0 bbb222 $YOUNG
example/busy-tool:1.0 ccc333 $OLD
<none>:<none> ddd444 $OLD
ghcr.io/autobleem2/autobleem-build:develop eee555 $OLD
ghcr.io/autobleem2/autobleem-build:0123abc fff666 $OLD
autobleem-build:latest ggg777 $OLD
autobleem-kernel-build:v1 hhh888 $OLD
autobleem-kernel-build:v2 iii999 $OLD
EOT
    echo "example/busy-tool:1.0" > "$FAKE_DIR/inuse"
}

run_script() {  # extra args are env assignments passed through env(1)
    OUT=$(env PATH="$WORK/bin:$PATH" "$@" bash "$SCRIPT" 2>"$WORK/err"); RC=$?
}

check() {  # check <name> <condition exit status>
    if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi
}

removed() { grep -qxF "rmi $1" "$FAKE_DIR/log"; }

setup
run_script DRY_RUN=0
check "exit 0" "$RC"
removed example/old-tool:1.0;            check "old unused image removed" $?
removed ddd444;                          check "old dangling-tag image removed by id" $?
! removed example/young-tool:2.0;        check "young image kept" $?
! removed example/busy-tool:1.0;         check "in-use image kept (rmi refuses)" $?
grep -q "in use - kept" <<< "$OUT";      check "in-use refusal is reported" $?
for ref in ghcr.io/autobleem2/autobleem-build:develop ghcr.io/autobleem2/autobleem-build:0123abc \
           autobleem-build:latest autobleem-kernel-build:v1 autobleem-kernel-build:v2 \
           eee555 fff666 ggg777 hhh888 iii999; do
    ! removed "$ref";                    check "keep-list image kept: $ref" $?
done

setup
touch "$FAKE_DIR/fail"
run_script DRY_RUN=0
[ "$RC" != 0 ];                          check "listing error = non-zero exit" $?
grep -q "cannot list docker images" "$WORK/err"; check "listing error has a clear message" $?
[ ! -s "$FAKE_DIR/log" ];                check "listing error removes nothing" $?

setup
run_script DRY_RUN=1
check "dry run exit 0" "$RC"
[ ! -s "$FAKE_DIR/log" ];                check "dry run removes nothing" $?
[ ! -e "$FAKE_DIR/other" ];              check "dry run prunes nothing" $?
grep -q "docker rmi example/old-tool:1.0" <<< "$OUT"; check "dry run prints what would be removed" $?
! grep -q "docker rmi autobleem-kernel-build" <<< "$OUT"; check "dry run does not list keep-list images" $?

setup
run_script DRY_RUN=0 KEEP_IMAGES="example/old-tool"
! removed example/old-tool:1.0;          check "KEEP_IMAGES override honoured" $?
removed autobleem-kernel-build:v1;       check "KEEP_IMAGES override replaces the default" $?

[ "$FAILS" = 0 ] && echo "all passed" || { echo "$FAILS failed"; exit 1; }
