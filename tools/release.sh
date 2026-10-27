#!/usr/bin/env bash
# Release what's merged on main: ./tools/release.sh 1.4.0   (docs/RASPBERRY_PI.md, Part 4)
#
# Checks main's latest CI run passed, then tags that commit v1.4.0 and pushes the tag. The
# release workflow builds the images (amd64 and arm64) with the version in them; then, on
# the server: ~/themi/update.sh 1.4.0. Nothing on your working copy changes.
set -euo pipefail

version="${1:-}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "usage: tools/release.sh 1.4.0" >&2
    exit 2
}
tag="v$version"

cd "$(dirname "$0")/.."
jj git fetch
commit="$(jj log -r 'main@origin' --no-graph -T 'commit_id')"
[ -n "$commit" ] || { echo "release: no main@origin" >&2; exit 1; }

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null \
    || git ls-remote --exit-code --tags origin "$tag" >/dev/null 2>&1; then
    echo "release: $tag exists already" >&2
    exit 1
fi

ci="$(gh run list --workflow CI --commit "$commit" --limit 1 --json status,conclusion \
    --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null || true)"
if [ "$ci" != "completed success" ]; then
    echo "release: CI on main ($commit) isn't green yet: ${ci:-no run found}" >&2
    exit 1
fi

echo "release: tagging ${commit:0:12} (main) as $tag"
git tag -a "$tag" -m "Themi $version" "$commit"
git push origin "$tag"
echo "release: pushed $tag; the images build in about ten minutes (gh run watch)."
echo "release: then, on the server: ~/themi/update.sh $version"
