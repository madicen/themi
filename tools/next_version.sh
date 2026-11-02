#!/usr/bin/env bash
# The version after the latest vX.Y.Z tag: tools/next_version.sh minor   (patch, minor, major)
#
# Prints the bare version (1.5.0). With no release tags yet, counts up from 0.0.0. Used by
# the release workflow's "Run workflow" button; tools/release.sh takes a version by hand.
set -euo pipefail

bump="${1:-}"
[[ "$bump" =~ ^(patch|minor|major)$ ]] || {
    echo "usage: tools/next_version.sh patch|minor|major" >&2
    exit 2
}

latest="$(git tag --list 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)"
IFS=. read -r major minor patch <<<"${latest#v}"
major="${major:-0}" minor="${minor:-0}" patch="${patch:-0}"

case "$bump" in
    major) echo "$((major + 1)).0.0" ;;
    minor) echo "$major.$((minor + 1)).0" ;;
    patch) echo "$major.$minor.$((patch + 1))" ;;
esac
