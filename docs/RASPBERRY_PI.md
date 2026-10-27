# Themi on a Raspberry Pi: a plan for painless deploys

A plan, not yet done. The aim: the Pi only ever runs a published, tested image. A release is
one tag on your laptop, and getting Themi onto a new Pi after a failure takes about fifteen
minutes. `docs/DEPLOY.md` stays the general guide; this is the Pi-specific path through it,
plus a few repo changes that make it smooth.

## The shape of it

```
laptop                      GitHub                         Raspberry Pi
------                      ------                         ------------
jj commit, push   ──►  CI: lint, tests, smoke-test
tag v1.4.0        ──►  release: build amd64 + arm64,
                        push ghcr.io/madicen/themi:1.4.0
                        deploy (optional): over Tailscale ──►  ~/themi/update.sh 1.4.0
                                                                 1. backup snapshot
                                                                 2. pull the new image
                                                                 3. restart
                                                                 4. wait for "healthy"
                                                                 5. unhealthy? roll back
```

Nothing is built on the Pi, and nothing on it is edited by hand after setup except `.env`.
Everything else is a script in the repo, so a rebuilt Pi comes out the same.

## Part 1: repo changes (done 2026-10-27)

1. **Images for the Pi.** `release.yml` builds for `linux/amd64` only. Add QEMU and
   `platforms: linux/amd64,linux/arm64`, so every tag publishes an image the Pi can run. The
   base image (`python:3.13-slim`) is multi-arch already; nothing else changes. The ARM
   build is slower (several minutes under emulation), which is fine for releases.
2. **`deploy/update.sh <version>`**, run on the Pi. It:
   - takes a backup snapshot first (`themi backup`), since migrations only go forward;
   - writes the new version into `.env` (`THEMI_VERSION`), keeping the old one as
     `THEMI_PREVIOUS_VERSION`;
   - runs `docker compose pull` and `up -d`, then waits up to two minutes for the
     container's own health check to say healthy;
   - if it doesn't, puts the old version back, restores the snapshot it just took (an older
     image refuses a database a newer one migrated), starts it again, and exits with an
     error, so you see it (and the deploy job fails).

   It's safe to run twice, and `update.sh` with no version re-pulls the current one.
3. **`deploy/bootstrap-pi.sh`**: everything in Part 2's steps 3 to 6, written so it can be run
   again safely. A dead SD card or SSD then means: flash, copy `.env`, run this, restore.
4. **`tools/release.sh 1.4.0`**: checks the working copy is clean and the tests pass, then
   tags and pushes. One command for a release.
5. **Optional: deploy on tag.** A `deploy` job after `release` joins your tailnet with
   Tailscale's GitHub Action (an OAuth client, tagged `tag:ci`) and runs
   `ssh themi@themi ~/themi/update.sh <version>`. Without it, you run that one line yourself
   after the release finishes. I'd start manual and add this once the manual path has worked
   a few times.
6. **`deploy/compose.yml` on a Pi**: `mem_limit: 700m` was sized for a 1 GB cloud VM; on a 4
   to 8 GB Pi it can go to 1.5 GB. Logs get rotated (see step 4 below).

Done, and how it turned out:
- `release.yml` builds `linux/amd64` and `linux/arm64` (QEMU) and passes the tag in as
  `THEMI_BUILD_VERSION`, which `themi --version` reports (the Dockerfile's `ARG`).
- `deploy/update.sh`: the database copy is SQLite's own online backup, made by Python in
  Themi's image on the data volume (`themi.db.before-<version>`), so it needs no backup
  storage and no tools on the host; the last three are kept (`KEEP_COPIES`). A storage
  backup is taken too when `THEMI_BACKUP_BUCKET` is set. A failed version's database is kept
  as `themi.db.failed-<version>`. Waits up to 180 s (`HEALTH_WAIT`).
- `tools/release.sh` tags `main@origin`, not the working copy, after checking main's latest
  CI run passed (`gh`), so a release is always what's merged and tested.
- `deploy/bootstrap-pi.sh`: steps 3 to 6 below, each checked before it changes anything.
- `THEMI_MEM_LIMIT` in `.env` sets the cap (`deploy/compose.yml`).
- Tests: `tests/integration/test_deploy_scripts.py` runs `update.sh` against a stand-in
  `docker` (no Docker here): upgrade, a failed health check rolling back the database, a
  failed pull changing nothing, going back by hand, pruning, the storage backup.
- Not done yet: the optional deploy-on-tag job (5), and a real run on Docker, which the first
  release and the Pi will be.

## Part 2: the Pi itself (you, with me checking)

### 1. Hardware
- A **Raspberry Pi 5** (4 or 8 GB) or a **Pi 4** (4 GB or more), its official power supply,
  and a case with a fan or heatsink.
- **A USB 3 SSD** (any small one; 128 GB is plenty), or an NVMe drive on a Pi 5 with an M.2
  HAT. Boot and run from it, not the SD card: Themi writes to its database all day, and SD
  cards wear out and corrupt under that.
- **Ethernet** if the router is near; Wi-Fi works, but wired is steadier for a server.

### 2. Flash the operating system
With **Raspberry Pi Imager** on your laptop, write **Raspberry Pi OS Lite (64-bit)** straight
to the SSD. In Imager's settings before writing:
- hostname `themi`, a user (say `themi`), your SSH public key, password login off;
- your time zone (America/Los_Angeles), keyboard and, if needed, Wi-Fi.

A Pi 5 boots from USB out of the box. A Pi 4 may need its bootloader set to USB boot first:
in Imager, *Choose OS → Misc utility images → Bootloader → USB Boot*, write that to an SD
card, boot the Pi with it once, then remove it.

### 3. First boot
```sh
ssh themi@themi.local
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades sqlite3
sudo dpkg-reconfigure -plow unattended-upgrades   # security updates install themselves
```

### 4. Docker
```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker themi        # log out and back in after this
```
Keep container logs from filling the disk, in `/etc/docker/daemon.json`:
```json
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
```
then `sudo systemctl restart docker`.

### 5. Tailscale
```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh              # log in; --ssh lets you (and the deploy job) in by name
sudo tailscale funnel --bg 8080      # https://themi.<tailnet>.ts.net reaches the website
```
Then nothing on the Pi needs to be open to the internet, and you can reach it from anywhere
as `themi`. (The website is published by Funnel; the Pi's own ports stay closed.)

### 6. Themi's folder
```sh
mkdir -p ~/themi && cd ~/themi
# from the laptop: scp deploy/compose.yml deploy/update.sh themi@themi:~/themi/
echo "<github token with read:packages>" | docker login ghcr.io -u madicen --password-stdin
```

## Part 3: moving Themi from this machine to the Pi

The order matters: **only one Themi may run with the real Telegram token**, or both poll and
messages get lost.

1. **Backups first, here.** Set up Backblaze B2 (DEPLOY.md section 7), add the four
   `THEMI_BACKUP_*` values to this machine's `.env`, restart, and run `themi backup`. This
   also proves backups work before you rely on them.
2. **The Pi's `.env`**: start from this machine's `.env` and change:
   - add `THEMI_IMAGE=ghcr.io/madicen/themi` and `THEMI_VERSION=<the tag>`;
   - `THEMI_PUBLIC_URL=https://themi.<tailnet>.ts.net`;
   - remove `THEMI_DB_PATH`, `THEMI_HTTP_HOST` and `THEMI_HTTP_PORT` (compose sets them).

   Keep **`THEMI_SECRET_KEY` exactly the same**: the Google, AI and Cozyla credentials in the
   database are encrypted with it. Then `chmod 600 .env`. Keep a copy in your password
   manager; it's the one file the Pi can't be rebuilt without.
3. **Google**: in the OAuth client, add the redirect URI
   `https://themi.<tailnet>.ts.net/auth/google/callback` (keep the 127.0.0.1 one for local
   work). Linked accounts keep working; the address only matters for new links and sign-in.
4. **The switch** (a few minutes of Themi being away):
   - here: stop `themi run`;
   - run `themi backup` once more, so the snapshot is the very latest;
   - on the Pi: `docker compose run --rm themi restore latest --yes`, then
     `docker compose up -d` and `docker compose logs -f`;
   - check: `/health` says ok, the website opens at the ts.net address, a Telegram message gets
     an answer, and the next Cozyla and calendar syncs go through.
5. **This machine afterwards** is for development only: `make dev` (the Telegram simulator),
   or a separate test bot token and its own database. Never the family's token again while the
   Pi runs.

Restoring from the backup, rather than copying the file across, means the move doubles as
the restore drill DEPLOY.md asks for.

## Part 4: everyday releases

```sh
jj git push                    # CI runs on the branch
tools/release.sh 1.4.0         # once it's green: tag and push
# release builds both images (about 10 minutes), then, with the deploy job on, the Pi
# updates itself; without it:
ssh themi ~/themi/update.sh 1.4.0
```

- **Migrations**: run on start, as now; `update.sh` has already taken a snapshot.
- **Rolling back by hand**: `~/themi/update.sh 1.3.2 --restore` puts the old version and the
  snapshot from before the upgrade back.
- **Version numbers**: a minor bump for each prompt or batch of fixes; `latest` on the Pi is
  avoided, so what runs is always a known tag.

## Part 5: keeping it healthy

- **Nightly backups** to B2 (Themi does these itself once configured), and a restore drill
  every few months (DEPLOY.md section 10).
- **Is it up?** Docker restarts it if it dies, and the health check marks it unhealthy if it
  hangs. For a nudge when the whole Pi is down, a free [healthchecks.io] check pinged every
  few minutes (a cron line with `curl`, only when `/health` is ok) emails you after a gap.
- **Disk**: logs are capped (step 4); the database is small. `df -h` now and then.
- **The OS** patches itself (unattended-upgrades). Reboot after kernel updates, at a quiet
  time: `sudo reboot`; Themi comes back on its own (`restart: unless-stopped`).
- **If the Pi dies**: a new SSD, Part 2's steps 2 and 3, `bootstrap-pi.sh`, the saved
  `.env`, `restore latest`, `up -d`. About fifteen minutes, all from the repo and the
  password manager.

[healthchecks.io]: https://healthchecks.io

## Decisions for you

1. **Pi 5 or Pi 4**, and SSD over USB or NVMe (Pi 5 only).
2. **Deploy on tag, or by hand** to start (I'd start by hand).
3. **When to move**: now, or after this machine has had backups running for a few nights.

## What's next

Part 1 is built. The first real test is a release: `tools/release.sh 0.2.0` once this is
merged, then watching the release workflow build both images. After that, the Pi (Part 2).
