# Deploying to your Hostinger Ubuntu VPS

Your server already runs other websites. Every step below is designed so those sites,
their Nginx configs, PM2 apps and SSL certificates are **never changed**. Read each
command's explanation before running it.

**What you need before starting**

* SSH access to the VPS as a user that can run `sudo`.
* A (sub)domain for the app, for example `videos.yourdomain.com`.
* A GitHub account. See [Connecting GitHub](#connecting-github).

## The plan, and how to undo it

| Step | What changes | How to undo |
| --- | --- | --- |
| 1. Inspect | nothing (read-only report) | — |
| 2. Install | adds the users `videodl` and `videodl-deploy`, the folders `/opt/video-downloader`, `/var/lib/video-downloader` and `/etc/video-downloader`, five systemd units, one Nginx site file, one sudoers file, and missing apt packages | `sudo video-downloader-rollback --disable`, then [Uninstall](#uninstall) |
| 3. DNS + HTTPS | one DNS record, one new certificate for the new domain | delete the record, `sudo certbot delete --cert-name <domain>` |
| 4. Deploy | a new folder under `/opt/video-downloader/releases` | `sudo video-downloader-rollback` |

## Step 1: Inspect the server (read-only)

On your computer, copy the repository's `scripts` folder to the server, or clone the repo
on the server (step 2 does that anyway):

```bash
ssh you@your-server-ip
git clone https://github.com/<you>/video-downloader.git ~/video-downloader   # downloads the code
cd ~/video-downloader
sudo bash scripts/server-inspect.sh 2>&1 | tee ~/inspect-report.txt         # prints a report, changes nothing
```

The report shows:

* the Ubuntu version, CPU, memory and disk space
* which ports are taken (the app wants 8010 and 3010)
* the domains your Nginx already serves
* your existing PM2 apps, Node, Python, FFmpeg and Redis

**Send the report back for review before step 2.** If ports 8010 or 3010 are in use,
pick others in step 2 (`--api-port 8020 --web-port 3020`). If Redis database 5 already
has keys, pick another with `--redis-db 6`.

## Step 2: Install (one time)

```bash
cd ~/video-downloader
less scripts/install-server.sh                      # read what it will do
sudo bash scripts/install-server.sh --domain videos.yourdomain.com
```

It prints the full plan and waits for you to type `y`. Then it:

1. Installs `ffmpeg`, `redis-server`, `sqlite3`, `curl` and `xz-utils`, **only if missing**.
   It never upgrades or removes packages.
2. Creates two users:
   * `videodl` runs the app. It has no password and can't log in.
   * `videodl-deploy` is what GitHub Actions logs in as. It can only upload releases and
     run the deploy and rollback commands.
3. Installs private copies of Python 3.12 (via uv), Node 24 and PM2 under
   `/opt/video-downloader/shared`, with checksums verified. Your existing Node and PM2 are
   not touched, and the app's PM2 has its own home folder, so `pm2 list` for your other
   sites won't show it.
4. Writes settings to `/etc/video-downloader/video-downloader.env`. That file holds the
   secrets, and only root and `videodl` can read it.
5. Installs systemd services: the API, two workers (`--workers 1`–`8`), the web UI, and a
   cleanup timer that runs every 5 minutes.
6. Adds a **new** Nginx site file `video-downloader.conf` for your domain only. It runs
   `nginx -t` first, and if the test fails it switches the new site off again, so your
   other sites keep working.

Optional extras:

* `--with-deno` adds Deno, the preferred sandbox for YouTube's JavaScript challenges.
  Node works too.
* `--yes` skips the confirmation prompt.

## Step 3: DNS and HTTPS

1. In Hostinger's DNS zone editor (or wherever your domain's DNS is), add an **A record**:
   name `videos`, value = your VPS IP.
2. Wait until `ping videos.yourdomain.com` shows your server IP.
3. Get a certificate. Certbot edits **only** the new `video-downloader.conf` site:

```bash
sudo certbot --nginx -d videos.yourdomain.com     # gets a free Let's Encrypt certificate and enables HTTPS
```

If Certbot isn't installed: `sudo apt install certbot python3-certbot-nginx`.
Certbot renews certificates automatically. To check: `sudo certbot renew --dry-run`.

After HTTPS works, turn on HSTS. Edit `/etc/nginx/sites-available/video-downloader.conf`,
remove the `#` before `add_header Strict-Transport-Security`, then run
`sudo nginx -t && sudo systemctl reload nginx`.

> Sign-in only works over HTTPS, because the session cookie is marked `Secure`.

## Step 4: First deploy

**Option A: from GitHub (recommended).** Set up [Connecting GitHub](#connecting-github),
then push to `main`. GitHub Actions runs the tests, builds a release, uploads it, and runs
`video-downloader-deploy` on the server.

**Option B: by hand.** On your computer:

```bash
scripts/build-release.sh                       # creates dist/video-downloader-<version>.tar.gz
scp dist/video-downloader-*.tar.gz you@your-server-ip:/tmp/
ssh you@your-server-ip
sudo mv /tmp/video-downloader-*.tar.gz /home/videodl-deploy/incoming/
sudo video-downloader-deploy /home/videodl-deploy/incoming/video-downloader-<version>.tar.gz
```

Every deploy does the same things:

1. Unpacks into a new folder.
2. Installs the Python packages.
3. Backs up the database to `/var/lib/video-downloader/backups`.
4. Applies database migrations.
5. Switches the `current` link to the new folder.
6. Restarts the services.
7. Checks `/api/health`. **If the check fails, it switches back automatically.**

## Step 5: Create your login

```bash
sudo video-downloader-cli create-admin yourname     # asks for a password (12+ characters)
```

Open `https://videos.yourdomain.com` and sign in.

To check the whole pipeline with a Creative Commons sample video:

```bash
VD_PASSWORD='your-password' python3 ~/video-downloader/scripts/smoke_test.py https://videos.yourdomain.com yourname
```

## Day-to-day commands

| Task | Command |
| --- | --- |
| Are the services running? | `systemctl status video-downloader-api video-downloader-web 'video-downloader-worker@*'` |
| Live logs | `journalctl -u 'video-downloader-*' -f` |
| Health | `curl -s https://videos.yourdomain.com/api/health` |
| Queue length | `redis-cli -n 5 llen rq:queue:video-downloader` |
| Change settings | `sudo nano /etc/video-downloader/video-downloader.env`, then `sudo systemctl restart video-downloader-api 'video-downloader-worker@*'` |
| Run cleanup now | `sudo video-downloader-cli cleanup` |
| Check tools | `sudo video-downloader-cli check` |
| Reset password | `sudo video-downloader-cli reset-password yourname` |
| Add a worker | `sudo systemctl enable --now video-downloader-worker@3`, and set `VD_WORKERS=3` in the env file |

## Rolling back

```bash
sudo video-downloader-rollback --list          # show releases (* = current)
sudo video-downloader-rollback                 # go back to the previous release
sudo video-downloader-rollback 20261108-1830-abc1234    # go to a specific release
sudo video-downloader-rollback --restore-db /var/lib/video-downloader/backups/app-20261108-183000.db
```

## Switching the app off

```bash
sudo video-downloader-rollback --disable
```

This stops and disables the app's services and takes its Nginx site offline. Code, data,
settings and the certificate are kept. `--enable` turns everything back on.

## Uninstall

Run `--disable` first. Then remove what the installer created. The installer's manifest
at `/etc/video-downloader/install-manifest.txt` lists everything it added. Each command
deletes only paths named `video-downloader` or `videodl`:

```bash
sudo rm -f /etc/systemd/system/video-downloader-*.service /etc/systemd/system/video-downloader-*.timer
sudo systemctl daemon-reload
sudo rm -f /etc/nginx/sites-available/video-downloader.conf* /etc/nginx/conf.d/video-downloader.conf*
sudo nginx -t && sudo systemctl reload nginx
sudo rm -f /etc/sudoers.d/video-downloader /usr/local/sbin/video-downloader-*
sudo rm -rf /opt/video-downloader /var/cache/video-downloader
# Only when you no longer need the database, history and settings:
sudo rm -rf /var/lib/video-downloader /etc/video-downloader
sudo userdel videodl; sudo userdel -r videodl-deploy
```

Packages that the manifest lists as `apt:` were installed for this app. Remove them only
if no other site uses them (Redis in particular).

## Nginx details

The site file answers only for your domain:

* `/api/*` goes to FastAPI on `127.0.0.1:8010`. Responses are not buffered, so video
  streams play smoothly. Login is limited to 10 per minute per IP.
* Everything else goes to the Next.js UI on `127.0.0.1:3010`.
* `client_max_body_size 8m` fits watermark uploads.
* The `limit_req_zone` names start with `vdl_` so they don't clash with your other sites.

Both app ports listen on `127.0.0.1` only, so no firewall changes are needed.

**Optional: faster file delivery.** Nginx can send files directly instead of Python.

1. Set `USE_X_ACCEL_REDIRECT=true` in the env file.
2. Let Nginx read the media folder: `sudo usermod -aG videodl www-data`, then
   `sudo chmod 750 /var/lib/video-downloader /var/lib/video-downloader/media`.
3. Restart Nginx and the API.

**Behind Cloudflare.** Add `set_real_ip_from` for Cloudflare's IP ranges and
`real_ip_header CF-Connecting-IP;` to the site. Otherwise rate limits count all visitors
as one.

## Connecting GitHub

1. Create an **empty private** repository on github.com named `video-downloader`.
   Don't add a README.
2. On your computer, in the project folder:

```bash
git remote add origin git@github.com:<your-username>/video-downloader.git   # tells git where GitHub is
git push -u origin main                                                      # uploads the code
```

3. Create a deploy key pair on your computer. It is used only by GitHub Actions:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/videodl_deploy -C "github-actions deploy" -N ""
```

4. Put the **public** key on the server:

```bash
cat ~/.ssh/videodl_deploy.pub | ssh you@your-server-ip "sudo tee -a /home/videodl-deploy/.ssh/authorized_keys"
```

5. In GitHub, go to **Settings → Secrets and variables → Actions → New repository secret**
   and add:

| Secret | Value |
| --- | --- |
| `VPS_HOST` | your server IP |
| `VPS_PORT` | your SSH port, if it isn't 22 |
| `VPS_SSH_KEY` | the content of `~/.ssh/videodl_deploy` (the **private** key) |
| `VPS_KNOWN_HOSTS` | the output of `ssh-keyscan -p 22 your-server-ip` |

6. Optional: under **Settings → Environments → production**, add yourself as a required
   reviewer, so every deploy waits for your click.

Workflows:

* **CI** runs backend tests, the frontend build and a shell-script lint on every push and
  pull request.
* **Server install test** runs the real installer, deploy and rollback on a fresh Ubuntu
  runner whenever deployment files change.
* **Deploy** runs after CI passes on `main`. It does nothing until the secrets exist.

Never commit `.env` files, keys, passwords or cookies. `.gitignore` blocks the usual
names, and the release builder refuses to package them.
