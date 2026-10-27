#!/usr/bin/env bash
# Deploy a Themi version on this server, safely (docs/RASPBERRY_PI.md, Part 1).
#
#   ./update.sh 1.4.0            upgrade (or move) to 1.4.0
#   ./update.sh                  pull the current version again and restart
#   ./update.sh 1.3.2 --restore  go back to 1.3.2 and the copy taken before leaving it
#
# An upgrade: pull the new image (nothing stops if that fails), copy the database on its
# volume, back it up to storage if that's set up, switch THEMI_VERSION in .env, restart, and
# wait for the container's health check. Not healthy in time: the old version and the copy
# go back, and this exits with an error. Migrations only go forward, so the copy is what
# makes going back possible.
set -euo pipefail

cd "$(dirname "$0")"
HEALTH_WAIT="${HEALTH_WAIT:-180}"   # seconds to wait for "healthy"
KEEP_COPIES="${KEEP_COPIES:-3}"     # database copies kept on the volume

die() { echo "update: $*" >&2; exit 1; }
say() { echo "update: $*"; }

[ -f .env ] || die "no .env here"
[ -f compose.yml ] || die "no compose.yml here"

current="$(sed -n 's/^THEMI_VERSION=//p' .env | tail -n 1)"
current="${current:-latest}"
target="${1:-$current}"
restore=false
[ "${2:-}" = "--restore" ] && restore=true
[[ "$target" =~ ^(latest|[0-9]+\.[0-9]+(\.[0-9]+)?)$ ]] || die "not a version: $target"

set_version() {
    if grep -q '^THEMI_VERSION=' .env; then
        sed -i "s/^THEMI_VERSION=.*/THEMI_VERSION=$1/" .env
    else
        echo "THEMI_VERSION=$1" >> .env
    fi
}

# Python in Themi's own image does the copying, so nothing else is needed on the host.
on_volume() {
    docker compose run --rm --no-deps -T --entrypoint python themi -c "$1" "${@:2}"
}

copy_database() {  # $1: the copy's name, on the data volume
    on_volume '
import sqlite3, sys
src = sqlite3.connect("/data/themi.db")
dst = sqlite3.connect("/data/" + sys.argv[1])
src.backup(dst)  # safe while Themi runs
dst.close(); src.close()
' "$1"
}

put_back() {  # $1: the copy to restore; the database it replaces is kept as $2
    on_volume '
import os, shutil, sys
data = "/data/"
if os.path.exists(data + "themi.db"):
    shutil.copy2(data + "themi.db", data + sys.argv[2])
for extra in ("themi.db-wal", "themi.db-shm"):
    if os.path.exists(data + extra):
        os.remove(data + extra)
shutil.copy2(data + sys.argv[1], data + "themi.db")
' "$1" "$2"
}

prune_copies() {
    on_volume '
import glob, os, sys
keep = int(sys.argv[1])
copies = sorted(glob.glob("/data/themi.db.before-*"), key=os.path.getmtime)
for old in copies[:-keep]:
    os.remove(old)
' "$KEEP_COPIES"
}

wait_healthy() {
    local id status waited=0
    id="$(docker compose ps -q themi)"
    [ -n "$id" ] || return 1
    while [ "$waited" -lt "$HEALTH_WAIT" ]; do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo gone)"
        case "$status" in
            healthy) return 0 ;;
            unhealthy|gone) return 1 ;;
        esac
        sleep 5
        waited=$((waited + 5))
    done
    return 1
}

if $restore; then
    copy="themi.db.before-$current"
    say "going back to $target with $copy (Themi stops for a moment)"
    set_version "$target"
    THEMI_VERSION="$target" docker compose pull themi
    docker compose stop themi
    put_back "$copy" "themi.db.replaced-$current"
    docker compose up -d themi
    wait_healthy || die "$target isn't healthy either; see: docker compose logs --tail 100"
    say "back on $target"
    exit 0
fi

say "pulling $target"
THEMI_VERSION="$target" docker compose pull themi || die "couldn't pull $target; nothing changed"

if [ "$target" = "$current" ]; then
    docker compose up -d themi
    wait_healthy || die "$target isn't healthy; see: docker compose logs --tail 100"
    say "restarted $target"
    exit 0
fi

copy="themi.db.before-$target"
say "copying the database to $copy"
copy_database "$copy"
if grep -q '^THEMI_BACKUP_BUCKET=.' .env; then
    docker compose exec -T themi themi backup || say "the backup to storage failed; going on"
fi

say "starting $target"
set_version "$target"
docker compose up -d themi
if wait_healthy; then
    prune_copies
    say "now on $target (was $current)"
    exit 0
fi

say "$target isn't healthy; going back to $current"
set_version "$current"
docker compose stop themi
put_back "$copy" "themi.db.failed-$target"
docker compose up -d themi
wait_healthy || die "back on $current, but it isn't healthy either; see: docker compose logs"
die "$target didn't start well; back on $current with the database from before"
