#!/usr/bin/env bash
# themi install: everything a Linux server or Raspberry Pi needs before Themi's website can
# take over (SP8b; docs/DEPLOY.md, "The short way"). Safe to run again: each step looks
# before it changes anything, and an existing .env is never replaced.
#
#   bash install.sh             (with compose.yml, update.sh and control.sh beside it)
#   curl -fsSL <raw url>/deploy/install.sh | bash
#
# It checks the machine, installs Docker, makes ~/themi with the short .env, offers to
# publish the website with Tailscale Funnel (and walks through making a Tailscale account),
# starts Themi, and prints the website's address and the claim code to set it up with.
#
# Settings, for running it without questions:
#   THEMI_HOME           the folder (default ~/themi)
#   THEMI_IMAGE          the image (default ghcr.io/madicen/themi)
#   THEMI_FUNNEL         yes or no: publish with Tailscale Funnel (default: ask)
#   THEMI_FILES_URL      where to fetch compose.yml and the scripts when they aren't beside this
#   THEMI_NONINTERACTIVE 1: never ask; take each question's default
#   THEMI_NO_RUNNER      1: leave out the host's runner for the website's Update button
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
HOME_DIR="${THEMI_HOME:-$HOME/themi}"
IMAGE="${THEMI_IMAGE:-ghcr.io/madicen/themi}"
FILES_URL="${THEMI_FILES_URL:-https://raw.githubusercontent.com/madicen/themi/main/deploy}"
HEALTH_URL="${THEMI_HEALTH_URL:-http://127.0.0.1:8080/health}"
FILES="compose.yml update.sh control.sh themi-control.path themi-control.service \
themi-control-check.service themi-control-check.timer"
PUBLIC_URL=""

step() { printf '\n== %s\n' "$*"; }
say() { printf '%s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }

# A question, answered from the terminal even when this script came through a pipe.
ask() {  # $1: the question, $2: the default answer
    local answer=""
    if [ -n "${THEMI_NONINTERACTIVE:-}" ] || ! { : </dev/tty; } 2>/dev/null; then
        printf '%s [%s]: %s\n' "$1" "$2" "$2"
        REPLY="$2"
        return
    fi
    read -r -p "$1 [$2]: " answer </dev/tty || true
    REPLY="${answer:-$2}"
}

yes_to() {  # $1: an answer
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        y | yes) return 0 ;;
        *) return 1 ;;
    esac
}

# A line of .env, as Compose reads it (the last one wins); empty when it isn't there.
setting() {
    [ -f "$HOME_DIR/.env" ] || return 0
    grep -E "^$1=" "$HOME_DIR/.env" | tail -n 1 | cut -d= -f2- || true
}

set_setting() {  # $1: the name, $2: the value; added only when it isn't there already
    if [ -z "$(setting "$1")" ]; then
        printf '%s=%s\n' "$1" "$2" >>"$HOME_DIR/.env"
        say "Added $1 to .env"
    fi
}

# ----- 1. the machine ------------------------------------------------------------------------

check_machine() {
    step "This machine"
    [ "$(uname -s)" = "Linux" ] || die "Themi installs on Linux (a server, or a Raspberry Pi)."
    case "$(uname -m)" in
        x86_64 | amd64 | aarch64 | arm64) ;;
        *) die "Themi's image is for 64-bit Intel/AMD or ARM; this is $(uname -m)." ;;
    esac
    [ "$(id -u)" != "0" ] || die "Run this as your own user, not root: it asks for sudo itself."
    command -v sudo >/dev/null || die "This needs sudo."
    command -v curl >/dev/null || die "This needs curl: sudo apt-get install -y curl"
    local memory
    memory="$(awk '/MemTotal/ { print int($2 / 1024) }' /proc/meminfo 2>/dev/null || echo 0)"
    if [ "${memory:-0}" -gt 0 ] && [ "$memory" -lt 900 ]; then
        say "This machine has ${memory} MB of memory; Themi wants about 1 GB. It may be slow."
    fi
    say "$(uname -m) Linux, as $(id -un): fine."
}

# ----- 2. Docker ---------------------------------------------------------------------------------

install_docker() {
    step "Docker"
    if command -v docker >/dev/null; then
        say "Docker is installed."
    else
        say "Installing Docker (from get.docker.com)..."
        curl -fsSL https://get.docker.com | sudo sh
    fi
    if ! id -nG "$(id -un)" | grep -qw docker; then
        sudo usermod -aG docker "$(id -un)"
        say "Added you to the docker group."
    fi
    if [ ! -f /etc/docker/daemon.json ]; then
        # Container logs capped, so they can't fill the disk.
        printf '%s\n' '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }' \
            | sudo tee /etc/docker/daemon.json >/dev/null
        sudo systemctl restart docker
    fi
}

# Docker, through sudo until the docker group applies at the next sign-in.
dock() {
    if docker info >/dev/null 2>&1; then
        docker "$@"
    else
        sudo docker "$@"
    fi
}

# ----- 3. the folder and .env --------------------------------------------------------------

make_folder() {
    step "Themi's folder: $HOME_DIR"
    mkdir -p "$HOME_DIR"
    local file
    for file in $FILES; do
        if [ -f "$HERE/$file" ] && [ "$HERE" != "$HOME_DIR" ]; then
            cp "$HERE/$file" "$HOME_DIR/$file"
        elif [ ! -f "$HOME_DIR/$file" ]; then
            curl -fsSL "$FILES_URL/$file" -o "$HOME_DIR/$file" \
                || die "Couldn't fetch $file from $FILES_URL. Put it beside this script."
        fi
    done
    chmod +x "$HOME_DIR/update.sh" "$HOME_DIR/control.sh"
    if [ -f "$HOME_DIR/.env" ]; then
        say ".env is there already; it's kept as it is."
    else
        printf '%s\n' "# Written by themi install. Everything else is set on Themi's website." \
            >"$HOME_DIR/.env"
    fi
    set_setting THEMI_IMAGE "$IMAGE"
    set_setting THEMI_VERSION latest
    chmod 600 "$HOME_DIR/.env"
}

# ----- 4. Tailscale Funnel -----------------------------------------------------------------

tailscale_address() {
    sudo tailscale status --json 2>/dev/null | python3 -c \
        'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' \
        2>/dev/null || true
}

publish() {
    step "Publishing the website"
    local wanted="${THEMI_FUNNEL:-}"
    if [ -z "$wanted" ]; then
        say "Tailscale Funnel gives Themi a private https:// address that works anywhere,"
        say "with nothing opened on your router. It's free for a family. Without it, the"
        say "website works only on this machine and your home network."
        ask "Set up Tailscale Funnel" "yes"
        wanted="$REPLY"
    fi
    if ! yes_to "$wanted"; then
        say "Skipped. Run this again any time to set it up."
        return
    fi
    if ! command -v tailscale >/dev/null; then
        say "First, a Tailscale account, if you don't have one:"
        say "  1. On your phone or computer, open https://login.tailscale.com/start"
        say "  2. Sign up with Google, Microsoft, Apple or GitHub. It's free."
        ask "Press Enter when you have an account" "done"
        say "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    if ! sudo tailscale status >/dev/null 2>&1; then
        say "Next, Tailscale prints a link: open it and sign in, to add this machine."
        sudo tailscale up
    fi
    local tries=0
    until sudo tailscale funnel --bg 8080; do
        tries=$((tries + 1))
        if [ "$tries" -ge 3 ]; then
            say "Funnel isn't on yet. Turn it on at the link above, then run this again."
            return
        fi
        say "Tailscale asks to turn on Funnel (and HTTPS) for your tailnet: open the link above,"
        say "say yes, then come back."
        ask "Press Enter when that's done" "done"
    done
    local address
    address="$(tailscale_address)"
    if [ -n "$address" ]; then
        PUBLIC_URL="https://$address"
        set_setting THEMI_PUBLIC_URL "$PUBLIC_URL"
    fi
}

# ----- 5. starting Themi -------------------------------------------------------------------

start() {
    step "Starting Themi"
    cd "$HOME_DIR"
    if ! dock compose pull; then
        say "Couldn't download Themi's image ($IMAGE)."
        say "If it's private, sign in first: docker login ghcr.io (with a token that can read"
        say "packages), then run this again."
        exit 1
    fi
    dock compose up -d
    local tries=0
    until curl -fsS "$HEALTH_URL" >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -lt 60 ] || die "Themi didn't come up. See: cd $HOME_DIR && docker compose logs"
        sleep 2
    done
    if [ -z "${THEMI_NO_RUNNER:-}" ] && command -v systemctl >/dev/null \
        && [ -d /run/systemd/system ]; then
        # The website's Update and Restart: the host's runner (docs/DEPLOY.md, section 9).
        "$HOME_DIR/control.sh" --install || say "(The runner for website updates didn't install.)"
    fi
}

finish() {
    step "Done"
    local address code
    address="${PUBLIC_URL:-$(setting THEMI_PUBLIC_URL)}"
    address="${address:-http://$(hostname -I 2>/dev/null | awk '{ print $1 }' || echo localhost):8080}"
    say "Themi's website: $address"
    code="$(cd "$HOME_DIR" && dock compose exec -T themi cat /data/claim-code 2>/dev/null || true)"
    if [ -n "$code" ]; then
        say "Open it and enter this claim code to set Themi up: $code"
    else
        say "This Themi is set up already: sign in there."
    fi
}

main() {
    check_machine
    install_docker
    make_folder
    publish
    start
    finish
}

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ] || [ -z "${BASH_SOURCE[0]:-}" ]; then
    main "$@"
fi
