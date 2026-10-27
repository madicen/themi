#!/usr/bin/env bash
# Prepare a Raspberry Pi (or any Debian machine) for Themi: docs/RASPBERRY_PI.md, Part 2,
# steps 3 to 6. Safe to run again: each step checks before it changes anything.
#
#   scp deploy/bootstrap-pi.sh deploy/compose.yml deploy/update.sh themi@themi.local:
#   ssh themi@themi.local ./bootstrap-pi.sh
#
# Afterwards: put .env in ~/themi (chmod 600), log in to ghcr.io, and restore or init.
set -euo pipefail

step() { echo; echo "== $*"; }
user="$(id -un)"
home_dir="$HOME/themi"

step "System updates, and security updates from now on"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades sqlite3 curl
echo 'unattended-upgrades unattended-upgrades/enable_auto_updates boolean true' \
    | sudo debconf-set-selections
sudo DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive unattended-upgrades

step "Docker"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
fi
if ! id -nG "$user" | grep -qw docker; then
    sudo usermod -aG docker "$user"
    echo "(log out and back in for the docker group to apply)"
fi
if [ ! -f /etc/docker/daemon.json ]; then
    # Container logs capped, so they can't fill the disk.
    echo '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }' \
        | sudo tee /etc/docker/daemon.json >/dev/null
    sudo systemctl restart docker
else
    echo "/etc/docker/daemon.json exists; left as it is"
fi

step "Tailscale"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! sudo tailscale status >/dev/null 2>&1; then
    sudo tailscale up --ssh    # prints a link to log in with
fi
sudo tailscale funnel --bg 8080 || echo "(turn on Funnel for this tailnet, then run this again)"

step "Themi's folder"
mkdir -p "$home_dir"
for file in compose.yml update.sh; do
    if [ -f "$HOME/$file" ] && [ ! -f "$home_dir/$file" ]; then
        mv "$HOME/$file" "$home_dir/$file"
    fi
done
[ -f "$home_dir/update.sh" ] && chmod +x "$home_dir/update.sh"
if [ -f "$home_dir/.env" ]; then
    chmod 600 "$home_dir/.env"
else
    echo "Next: put .env in $home_dir (chmod 600; keep a copy in a password manager)"
fi

step "Done"
address="$(sudo tailscale status --json 2>/dev/null | python3 -c \
    'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' || true)"
echo "Website address: https://${address:-<this machine>.<tailnet>.ts.net}"
echo "Then: cd $home_dir && docker login ghcr.io && docker compose pull"
echo "      docker compose run --rm themi restore latest --yes   (or: themi init)"
echo "      docker compose up -d"
