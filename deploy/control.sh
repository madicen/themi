#!/usr/bin/env bash
# The host's side of updates asked for on Themi's website (D3a, D3b; docs/DEPLOY.md, section 9).
#
#   ./control.sh             run the request in control/request.json, if there is one
#   ./control.sh --check     only look up the newest release, for the website to show
#   ./control.sh --install   make control/, install the systemd units, start watching
#
# Themi can't update itself (it never gets Docker), so it writes control/request.json and
# systemd runs this. The request is moved aside first, so it runs once, and checked: an
# action of "update" or "restart" and nothing else. An update goes to the newest release on
# GitHub; a restart pulls the running version again. Either way update.sh does the work,
# with its copy of the database and its way back. How it went goes in control/result.json;
# control/runner.json says this is installed and which release is the newest.
set -euo pipefail

cd "$(dirname "$0")"
GITHUB_API="${GITHUB_API:-https://api.github.com}"
CONTAINER_UID="${CONTAINER_UID:-10001}"   # the user Themi runs as in its image
TAIL_LINES=40

die() { echo "control: $*" >&2; exit 1; }
say() { echo "control: $*"; }

# A value as Compose reads it: the last one wins, quotes come off, and so does a comment
# after it ("THEMI_REPO=owner/repo   # why").
setting() {
    python3 - "$1" <<'PY' 2>/dev/null
import re, sys
value = ""
for line in open(".env"):
    key, sep, raw = line.rstrip("\n").partition("=")
    if sep and key == sys.argv[1]:
        value = raw.strip()
quoted = re.fullmatch(r"""(["'])(.*?)\1\s*(#.*)?""", value)
print(quoted.group(2) if quoted else re.sub(r"\s+#.*", "", value))
PY
}

# Written whole or not at all, from KEY=VALUE arguments (VALUE "-" is null; an int stays one).
write_json() {
    python3 - "$@" <<'PY'
import json, os, sys
path, pairs = sys.argv[1], sys.argv[2:]
value = {}
for pair in pairs:
    key, _, raw = pair.partition("=")
    value[key] = None if raw == "-" else int(raw) if raw.isdigit() and key == "id" else raw
temp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
with open(temp, "w") as out:
    json.dump(value, out)
    out.write("\n")
os.chmod(temp, 0o644)
os.replace(temp, path)
PY
}

now() { date -u +%Y-%m-%dT%H:%M:%S+00:00; }

# The repo releases come from: THEMI_REPO, or ghcr.io/<owner>/<repo> from THEMI_IMAGE.
repo() {
    local repo image
    repo="$(setting THEMI_REPO)"
    if [ -z "$repo" ]; then
        image="$(setting THEMI_IMAGE)"
        repo="$(echo "$image" | sed -n 's#^ghcr\.io/\([^/:]*/[^/:]*\).*#\1#p')"
    fi
    [[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || return 1
    echo "$repo"
}

# The newest release's version (v1.5.0 -> 1.5.0), or "-" and why it couldn't be found.
lookup() {
    local repo token
    repo="$(repo)" \
        || { echo "- THEMI_REPO or THEMI_IMAGE in .env doesn't name a GitHub repository"; return 0; }
    token="$(setting THEMI_GITHUB_TOKEN)"   # only for a private repository
    # The token goes in on stdin, so it never shows in the process list. The answer comes
    # back with its HTTP status on a last line of its own.
    { [ -n "$token" ] && printf 'Authorization: Bearer %s\n' "$token"; true; } \
        | { curl -sS --max-time 20 -w '\n%{http_code}' -H "Accept: application/vnd.github+json" \
            -H @- "$GITHUB_API/repos/$repo/releases/latest" 2>/dev/null || true; } \
        | python3 -c '
import json, re, sys
body, _, code = sys.stdin.read().rpartition("\n")
repo, token = sys.argv[1:]
try:
    found = json.loads(body)
except ValueError:
    found = None
tag = str(found.get("tag_name", "")).removeprefix("v") if isinstance(found, dict) else ""
if re.fullmatch(r"\d+\.\d+\.\d+", tag):
    print(tag)
elif tag:
    print(f"- the newest release in {repo} is {tag}, not a version like v1.2.3")
elif code == "401":
    print("- GitHub turned down THEMI_GITHUB_TOKEN; it may have expired "
          "(a public repository needs none)")
elif code == "403":
    print(f"- GitHub refused: too many lookups for now, or the token can not see {repo}")
elif code == "404":
    print(f"- no release in {repo}" + ("" if token else
          ", or it is private and needs THEMI_GITHUB_TOKEN"))
else:
    print("- could not reach GitHub")
' "$repo" "${token:+token}" 2>/dev/null || echo "- could not read what GitHub said"
}

newest() {  # the version alone, or nothing
    local found
    found="$(lookup)"
    [ "${found%% *}" = "-" ] || echo "$found"
}

current_version() {
    local version
    version="$(setting THEMI_VERSION)"
    echo "${version:-latest}"
}

note_runner() {  # $1: the newest release, if known
    local installed
    installed="$(python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("installed_at") or "")
except Exception:
    print("")
' control/runner.json)"
    write_json control/runner.json "installed_at=${installed:-$(now)}" "newest=${1:--}" \
        "checked_at=$(now)"
}

install() {
    local user group units
    user="$(id -un)"
    group="$(id -gn)"
    units="$HOME/.config/systemd/user"
    # Themi (uid 10001 in its container) writes requests here; this user reads and moves
    # them. setgid keeps new files in this user's group.
    if [ ! -d control ]; then
        sudo install -d -m 2770 -o "$CONTAINER_UID" -g "$group" control
    else
        sudo chown "$CONTAINER_UID:$group" control
        sudo chmod 2770 control
    fi
    mkdir -p "$units"
    for unit in themi-control.path themi-control.service themi-control-check.service \
        themi-control-check.timer; do
        [ -f "$unit" ] || die "$unit isn't here; copy it next to control.sh"
        cp "$unit" "$units/$unit"
    done
    sudo loginctl enable-linger "$user"   # runs without anyone logged in
    systemctl --user daemon-reload
    systemctl --user enable --now themi-control.path themi-control-check.timer
    note_runner "$(newest)"
    say "installed: the website's Update and Restart buttons work now"
    grep -q '^THEMI_CONTROL_DIR\|/control' compose.yml \
        || say "compose.yml doesn't mount ./control yet; copy the new one from deploy/"
}

run_request() {
    local taken id action version current target found output status to
    [ -f control/request.json ] || { note_runner "$(newest)"; return 0; }
    taken="control/request.taken"
    mv control/request.json "$taken"   # first, so it runs once
    read -r id action version < <(python3 -c '
import json, sys
try:
    r = json.load(open(sys.argv[1]))
except Exception:
    r = {}
r = r if isinstance(r, dict) else {}
rid = r.get("id")
print(rid if isinstance(rid, int) and not isinstance(rid, bool) else "-",
      r.get("action") if r.get("action") in ("update", "restart") else "-",
      r.get("version") if r.get("version") in ("newest", "current") else "-")
' "$taken")
    rm -f "$taken"
    current="$(current_version)"
    if [ "$id" = "-" ] || [ "$action" = "-" ] || [ "$version" = "-" ] \
        || { [ "$action" = "update" ] && [ "$version" != "newest" ]; } \
        || { [ "$action" = "restart" ] && [ "$version" != "current" ]; }; then
        write_json control/result.json "id=$id" state=refused "from=$current" "to=$current" \
            "detail=not a request this runner knows" "finished_at=$(now)"
        die "refused a request it doesn't know"
    fi

    target="$current"
    if [ "$action" = "update" ]; then
        found="$(lookup)"
        target="${found%% *}"
        if [ "$target" = "-" ]; then
            note_runner ""
            write_json control/result.json "id=$id" state=failed "from=$current" "to=-" \
                "detail=couldn't find the newest release on GitHub: ${found#- }" \
                "finished_at=$(now)"
            die "couldn't find the newest release: ${found#- }"
        fi
        note_runner "$target"
        if [ "$target" = "$current" ]; then
            write_json control/result.json "id=$id" state=done "from=$current" "to=$current" \
                "detail=already on $current" "finished_at=$(now)"
            say "already on $current"
            return 0
        fi
    fi

    write_json control/result.json "id=$id" state=running "from=$current" "to=$target" \
        "detail=-" "finished_at=-"
    say "$action: $current -> $target"
    status=0
    if [ "$action" = "update" ]; then
        output="$(./update.sh "$target" 2>&1)" || status=$?
    else
        output="$(./update.sh 2>&1)" || status=$?
    fi
    echo "$output"
    to="$target"
    write_json control/result.json "id=$id" "state=$([ "$status" = 0 ] && echo done || echo failed)" \
        "from=$current" "to=$to" "detail=$(echo "$output" | tail -n "$TAIL_LINES")" \
        "finished_at=$(now)"
    [ "$action" = "update" ] || note_runner "$(newest)"
    return "$status"
}

[ -f .env ] || die "no .env here"
case "${1:-}" in
    --install) install ;;
    --check) [ -d control ] || die "no control folder; run ./control.sh --install"
             note_runner "$(newest)" ;;
    "") [ -d control ] || die "no control folder; run ./control.sh --install"
        run_request ;;
    *) die "usage: control.sh [--check | --install]" ;;
esac
