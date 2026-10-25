# Deploying Themi

This guide moves Themi from a laptop to a small cloud server. When it's done:

- the server runs the Telegram bot, the scheduler and the website in one container
- the website is reachable over HTTPS at a stable Tailscale Funnel address
- the database is backed up every night, encrypted, to Cloudflare R2 or Backblaze B2

Plan on an evening for the first deployment, and about two minutes for each
upgrade after that.

> **Prices and free tiers change.** Every figure below was checked on
> **2026-10-25** against the sources linked in each section. Check the
> provider's own page again before you sign up.

---

## 1. Before you start

You need these, most of them from the local setup in the README:

- The **Telegram bot token**. The family bot is not the test bot.
- **`THEMI_SECRET_KEY`** (`themi keygen` makes one). This key encrypts every stored token
  and every backup. **Without it, the backups can't be read.** Keep a copy in a password
  manager, away from the server.
- The **Google OAuth client** id and secret (README: "Google Cloud setup"). Its redirect
  address changes in step 6.
- A **Gemini API key**, or another AI backend, for each person.
- Optionally, the OurGroceries login.

If Themi already runs on your laptop, you can bring its data across. Take a backup there
(section 7) and restore it on the server (section 10), or copy the `.db` file across with
Themi stopped.

## 2. Choose a host

Themi needs about 300 to 500 MB of RAM, under 1 GB of disk, and outbound internet. It needs
no open inbound ports, because Telegram is polled and Funnel tunnels the website. Here are
the options I checked:

| Host | What you get | Cost, as checked | Watch out for |
| ---- | ------------ | ---------------- | ------------- |
| **Google Cloud e2-micro** (recommended start) | 2 shared vCPUs, 1 GB RAM, 30 GB standard disk | VM free in us-west1, us-central1 or us-east1. **The public IPv4 address costs $0.005/hour, about $3.65 a month.** | Use a *standard* disk, since the console defaults to *balanced*, which isn't free. Free egress is only 1 GB a month. |
| **Oracle Cloud Always Free** (Arm A1) | Up to 4 OCPU and 24 GB per Oracle's docs, though reports say this was halved in June 2026 | Free | Capacity is often unavailable. Idle VMs (under about 20% CPU, network and memory over 7 days) can be reclaimed. |
| **Hetzner Cloud** CX23 | 2 vCPU, 4 GB RAM, 40 GB | About €5.49/month plus €0.50 for IPv4, excluding VAT (after the June 2026 price rise) | EU and US locations. Best value among paid options. |
| **AWS Lightsail** | The $5 plan is 512 MB, which is too small. The $7 plan has 1 GB. | $7/month for 1 GB | Simple, but less memory for the money. |
| **A spare PC or Raspberry Pi at home** | Whatever it has | Electricity | Data stays home, and it can run Ollama too. Same steps from section 4. |

The plan called the e2-micro free. In fact it costs about $3.65 a month for its IPv4
address, which Google started charging for in February 2024. A VM without a public address
would need Cloud NAT to reach the internet, and that costs more. So budget about $3.65 a
month, or pick Hetzner for 4 GB of RAM at a little more.

Sources:
- Google Compute Engine free tier: <https://cloud.google.com/free/docs/compute-getting-started>
- Google VPC pricing (external IPs): <https://cloud.google.com/vpc/pricing>
- Google's announcement of external IPv4 pricing:
  <https://cloud.google.com/vpc/pricing-announce-external-ips>
- Oracle Always Free resources: <https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm>
- Report of the Oracle cut: <https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/>
- Hetzner's June 2026 prices: <https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do>
- Lightsail bundles: <https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html>

## 3. Create the server

On Google Cloud, choosing the e2-micro:

1. Use your existing project, or a new one, in the Cloud console. **Compute Engine → VM
   instances → Create instance.**
2. **Region:** `us-west1`, `us-central1` or `us-east1`. Only these are free.
3. **Machine type:** E2, `e2-micro`.
4. **Boot disk:** Debian 12, **Standard persistent disk**, 30 GB. Change it from Balanced.
5. **Networking:** keep the external IPv4 address, which costs about $3.65 a month as above.
   Choose the **Standard** network tier. Leave HTTP and HTTPS traffic unticked, because
   nothing needs to come in.
6. Create it, then click **SSH** to open a terminal on it.

On other hosts: any recent Debian or Ubuntu with SSH access works the same from here.

With 1 GB of RAM, add a swap file so that an image pull or a burst of work can't crash
the server:

```sh
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 4. Install Docker

Use Docker's own packages. The distribution's `docker.io` is often too old for
`docker compose`.

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # then log out and back in
docker compose version            # should print v2.x
```

Docker's install guide: <https://docs.docker.com/engine/install/debian/>

## 5. Get Themi onto the server

Pushing a version tag (`git tag v1.0.0 && git push --tags`) makes the release workflow
publish the image to `ghcr.io/<owner>/<repo>`. The repository has to be on GitHub first.
If it's private, the image is private too. Create a GitHub token with `read:packages`, and
log in once on the server:

```sh
echo "<token>" | docker login ghcr.io -u <github-user> --password-stdin
```

Then:

```sh
mkdir -p ~/themi && cd ~/themi
curl -fsSLO https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/compose.yml
# (or copy deploy/compose.yml across with scp)
nano .env          # see below
chmod 600 .env     # only you can read it
```

`.env` needs at least these lines. `.env.example` lists everything else:

```sh
THEMI_IMAGE=ghcr.io/<owner>/<repo>
THEMI_VERSION=1.0.0            # or latest
THEMI_SECRET_KEY=...           # the same key as before, if you're bringing data across
TELEGRAM_BOT_TOKEN=...
THEMI_PUBLIC_URL=https://<machine>.<tailnet>.ts.net   # from step 6
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
# backups: step 7
```

First run:

```sh
docker compose pull
docker compose run --rm themi init        # the family and the first admin
docker compose run --rm themi invite Erin # each person, if init didn't
docker compose up -d
docker compose logs -f                    # Ctrl-C to stop watching
```

If you have no registry, `docker compose -f compose.yml build` won't work, because the file
names an image. Copy the repository across instead, and use the repository's own
`docker-compose.yml` there.

## 6. Publish the website with Tailscale Funnel

Funnel gives the server a fixed `https://<machine>.<tailnet>.ts.net` address. Tailscale
provides the certificate, and no ports are opened. Google sign-in needs that HTTPS address.

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                    # opens a login link; log in with your Tailscale account
sudo tailscale funnel --bg 8080      # publishes 127.0.0.1:8080 on https port 443
tailscale funnel status              # shows the public address
```

Funnel needs HTTPS certificates and MagicDNS turned on for the tailnet, plus a `funnel`
attribute in the tailnet policy. The first `tailscale funnel` command offers to set these
up. Funnel can only listen on ports 443, 8443 and 10000. The address can take about ten
minutes to reach public DNS. Themi listens on 8080 locally, and Funnel serves it on 443.

Then:

1. Put the address in `.env` as `THEMI_PUBLIC_URL`, and run `docker compose up -d`.
2. In Google Cloud, under **Google Auth Platform → Clients**, add the authorised redirect
   URI `https://<machine>.<tailnet>.ts.net/auth/google/callback`.
3. Open `https://<machine>.<tailnet>.ts.net/health`. It should answer `{"status": "ok", ...}`.

Tailscale's free Personal plan covers this. It was reorganised in April 2026 and now
covers 6 users, which is more than enough.

Sources:
- Funnel: <https://tailscale.com/docs/features/tailscale-funnel>
- The `tailscale funnel` command: <https://tailscale.com/kb/1311/tailscale-funnel>
- Plan changes, from a secondary source:
  <https://costbench.com/software/business-vpn/tailscale/free-plan>

## 7. Turn on nightly backups

Each night Themi copies the live database with SQLite's online backup. It compresses the
copy, encrypts it with `THEMI_SECRET_KEY` and uploads it. Snapshots older than 30 days are
deleted, but the newest one is always kept. If backups keep failing for two days, the
admins get a Telegram message each day.

**Cloudflare R2.** The free tier is 10 GB-months of Standard storage, 1 million Class A and
10 million Class B operations a month, and free egress. A family's snapshots are a few MB,
so this costs nothing.

1. In Cloudflare: **R2 → Create bucket**, named for example `themi-backups`.
2. **R2 → Manage API tokens → Create API token**, with **Object Read & Write**, applied to
   that bucket only.
3. In `.env`:

   ```sh
   THEMI_BACKUP_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
   THEMI_BACKUP_BUCKET=themi-backups
   THEMI_BACKUP_ACCESS_KEY_ID=<access key id>
   THEMI_BACKUP_SECRET_ACCESS_KEY=<secret access key>
   # THEMI_BACKUP_REGION=auto          (the default; right for R2)
   # THEMI_BACKUP_KEEP_DAYS=30
   ```

**Backblaze B2.** The first 10 GB are free. Downloads are free up to three times what you
store, and the API calls backups use cost nothing at this scale.

1. Create a **private** bucket, and an application key limited to it.
2. The bucket page shows its S3 endpoint, for example `s3.us-west-004.backblazeb2.com`:

   ```sh
   THEMI_BACKUP_ENDPOINT=https://s3.us-west-004.backblazeb2.com
   THEMI_BACKUP_REGION=us-west-004
   THEMI_BACKUP_BUCKET=...
   THEMI_BACKUP_ACCESS_KEY_ID=<keyID>
   THEMI_BACKUP_SECRET_ACCESS_KEY=<applicationKey>
   ```

Restart Themi and check that it works:

```sh
docker compose up -d
docker compose run --rm themi backup          # "Backup saved themi/themi-....sqlite.gz.enc."
docker compose run --rm themi backup --list
```

Sources:
- R2 pricing: <https://developers.cloudflare.com/r2/pricing/>
- B2 pricing, from a secondary source; check Backblaze's own page:
  <https://upstash.com/blog/backblaze-b2-pricing-explained-2026.md>

## 8. Secrets

- **Where they live:** only in `~/themi/.env` on the server (`chmod 600`), and in your
  password manager. They never go in git: `.env` is ignored. CI secrets go in GitHub's
  repository settings.
- **In the database:** tokens and keys are encrypted with `THEMI_SECRET_KEY`. Logs redact
  them.
- **`THEMI_SECRET_KEY`:** there's no key rotation yet. Changing it makes stored tokens and
  old backups unreadable, so keep it as it is.
- **If the server is lost:** every secret in `.env` can be recreated (tokens re-issued,
  Gmail linked again), except `THEMI_SECRET_KEY`. That's why it goes in the password
  manager.
- **If a token leaks:**
  - Telegram: revoke it with @BotFather `/revoke`.
  - Google: delete the OAuth client secret and make a new one.
  - R2 or B2: delete the API key.
  - Then update `.env` and run `docker compose up -d`.

## 9. Upgrades

```sh
cd ~/themi
docker compose run --rm themi backup     # a fresh snapshot first
# set THEMI_VERSION in .env to the new version (or leave it at latest)
docker compose pull && docker compose up -d
docker compose logs --tail 50            # migrations run on startup; look for errors
```

An older image refuses to open a database that a newer one has migrated. So to roll back,
restore the snapshot from before the upgrade (section 10), then start the older version.

## 10. Restore drill

Do this once right after setting up backups, and then every few months. Restoring is only
proven once it has been done.

**Check the newest snapshot on the server** (this changes nothing):

```sh
docker compose run --rm themi restore latest --dry-run
# Snapshot themi/themi-20261025T031500Z.sqlite.gz.enc from 2026-10-25T03:15:00+00:00
#   integrity: ok; schema 24; members 2, tasks 14, ...
```

**A full restore**, for real, onto a broken or new server:

```sh
docker compose stop                     # Themi must not have the database open
docker compose run --rm themi restore latest --yes
docker compose up -d
```

The current database is never deleted. It's renamed to
`themi.db.before-restore-<time>` on the same volume.

**A drill without touching production:** on a laptop with the same `.env` (the same
`THEMI_SECRET_KEY` and backup settings), run `THEMI_DB_PATH=/tmp/drill.db themi restore
latest --yes`. Then `THEMI_DB_PATH=/tmp/drill.db THEMI_DISABLE_TELEGRAM=1 themi run`, and
look around the website at `http://localhost:8080`.

## 11. Troubleshooting

| Symptom | Likely cause, and what to do |
| ------- | ---------------------------- |
| `docker compose up` says `set THEMI_IMAGE in .env` | `.env` is missing that line, or it's in another directory. Run compose from `~/themi`. |
| `pull access denied` from ghcr.io | The image is private. Run `docker login ghcr.io` with a `read:packages` token. |
| The container restarts again and again | Read `docker compose logs`. "Themi can't start:" lists the settings to fix. |
| `database is at schema version N, but this Themi only knows up to M` | An older image is running against a newer database. Use the newer version, or restore a pre-upgrade snapshot. |
| The bot doesn't answer | Check `docker compose logs` for Telegram errors. A second copy of the bot polling with the same token (your laptop?) steals the updates, so stop it. |
| The website times out from outside | `tailscale funnel status` should list 443 → `http://127.0.0.1:8080`. Re-run `sudo tailscale funnel --bg 8080`. DNS can take about 10 minutes the first time. |
| Google sign-in says `redirect_uri_mismatch` | The callback in Google Cloud must be exactly `THEMI_PUBLIC_URL` + `/auth/google/callback`. |
| `Backup failed`, with `HTTP 403: SignatureDoesNotMatch` | Wrong secret key, or wrong `THEMI_BACKUP_REGION` (R2 needs `auto`; B2 needs its region). |
| `Backup failed`, with `HTTP 404: NoSuchBucket` | The bucket name or endpoint is wrong. For R2, the endpoint has your account id in it. |
| `restore` says `wrong THEMI_SECRET_KEY` | The key isn't the one the snapshot was made with. Use the copy from your password manager. |
| The server is very slow, or out of memory | `free -h`. Make sure the swap file is on. An e2-micro can't run a local model; run Ollama at home and reach it over Tailscale. |
| A surprise cloud bill | Look in Google Cloud billing for a *balanced* disk, a reserved static IP that isn't in use, or egress over 1 GB. |
