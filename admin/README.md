# The admin panel

`https://autobleem.retromenele.pl/admin/` - what the builders are doing, what each channel holds, the build
server's health, and the release team's buttons (a nightly, a promotion, cancel / re-run, withdraw, republish
the page). The plan and the reasons: `autobleem-main`'s `docs/archive/admin-panel-plan.md`.

The page has six tabs (the Download stats tab, release team only, is described at the end). **Builds** shows running and finished runs as cards with progress, job lists, steps and durations;
the queue of waiting runs and jobs; and the self-hosted runners and their active jobs. **Releases** holds the channels,
nightly and promotion actions, and withdraw/republish buttons. **Store** lists the site's catalogs
(`store/<platform>/catalog.json`, read-only). **Server** shows the build server's health. **Audit** is the release
team's action log.

- `app/` - the service (FastAPI): the JSON API under `/admin/api/` and the page (`app/static/index.html`).
- `tests/` - over a fake GitHub: `python -m pytest -q` here (`pip install -r requirements.txt pytest`).
- `Dockerfile`; `docker/repo/compose.yml` runs it (profile `admin`) with oauth2-proxy next to the site, and
  `docker/repo/Caddyfile` routes `/admin` and `/oauth2/` to them on the HTTPS name.

## Setting it up (the owner, once)

1. **The GitHub App** - organisation settings -> Developer settings -> GitHub Apps -> New GitHub App:
   - name `autobleem-admin`, homepage `https://autobleem.retromenele.pl/`;
   - **Callback URL** `https://autobleem.retromenele.pl/oauth2/callback`; "Request user authorization (OAuth)
     during installation" off; webhook off;
   - repository permissions: **Actions: read and write**, **Contents: read and write**, Metadata: read;
     organisation permissions: **Members: read**, **Self-hosted runners: read**, **Packages: read**;
   - "Only on this account"; create it, then **Generate a private key** (a `.pem` downloads) and **Generate a
     new client secret**; **Install** it on the `autobleem2` organisation, all repositories.
2. **The team** - a team `release-managers` in the organisation, with whoever may press the buttons.
3. **Telegram** (optional) - a bot from @BotFather (its token) and the chat it writes to (its id - send the bot
   a message, then `https://api.telegram.org/bot<token>/getUpdates` shows the chat id).
4. **On the build server**, in the site's checkout of this repository: `cp admin/.env.example admin/.env`, fill
   it in (the App id, the client id and secret, a cookie secret, Telegram), put the private key at
   `admin/app-key.pem` (`chmod 600` both), then from `docker/repo/`:
   `docker compose --profile admin up -d --build` - this also restarts Caddy with the new routes.
5. **For the workflows** (`autobleem-main`'s nightly.yml and promote.yml): in autobleem-main's settings, the
   variable **`AB_ADMIN_APP_ID`** (the App id) and the secret **`AB_ADMIN_APP_KEY`** (the `.pem`'s text), and
   `AB_CI_ENABLED=true` there and on autobleem-repo (withdraw.yml, page.yml).

Then `https://autobleem.retromenele.pl/admin/` asks for the GitHub login once; an org member sees the page,
a `release-managers` member also its buttons.

## The Teams tab's feed

The tab reads a private `teams.json` (`AB_ADMIN_TEAMS_FILE`, default `/feed/teams.json`), which the company's
tooling copies to `~/admin-data/` on the build server; `docker/repo/compose.yml` mounts that directory
(`ADMIN_FEED_DIR`) read-only into the admin service only. Caddy serves `/srv/repo` and nothing else, so the
file is not reachable from the web. When it is missing or older than 60 minutes the tab says "no source" and why.

## For scripts and Claude sessions

The same API with your own GitHub token as the bearer - the same rules as the browser, recorded in the audit
log as `via api`:

```
curl -H "Authorization: Bearer $(gh auth token)" https://autobleem.retromenele.pl/admin/api/status
curl -H "Authorization: Bearer $(gh auth token)" -H "Content-Type: application/json" \
     -d '{"platforms":["psc"],"dry_run":true}' https://autobleem.retromenele.pl/admin/api/nightly
```

`GET` `me`, `status`, `channels`, `health`, `audit`, `store`, `promote/preview?kind=alpha&version=` ; `POST` `nightly`,
`promote`, `runs/<repo>/<id>/cancel`, `runs/<repo>/<id>/rerun`, `withdraw`, `page`. A browser's `POST` also
needs the header `X-AB-Request: 1` (the page sends it; a cross-site form cannot).

## The build server's disk

`.github/workflows/cleanup.yml` runs every night at 01:30 UTC, before the nightly assembly (and on demand, with a
dry run): `tools/server_cleanup.sh` removes the old `autobleem-build:<sha>` image tags, dangling images, stopped
containers and build cache unused for three days, then the page is regenerated, which prunes the site's
nightlies to one (`NIGHTLY_KEEP` in `tools/repo_index.py`; the one before stays while the newest has no images
yet). The panel's Health row turns red under `AB_LOW_DISK_GB` (10) free, and Telegram says so once.

## Download stats (the download counter)

The **Download stats** tab (release team only; `GET /admin/api/downloads` answers 403 to a plain member) shows how
often each file of the site was downloaded: a summary on opening (today / 7 days / 30 days / all time, the top 10
files of the last 7 days, the last 30 days by platform and by channel), then the totals by group, by version and
for every file. Nothing of it is public.

- **What is counted**: a `GET` answered `200` for a file of a download type (`DOWNLOAD_EXT` in `app/downloads.py`:
  zip, gz, xz, img, pdf, exe ...), per UTC day. Not counted: `HEAD`, `304`, `404`, `206` (a resumed or ranged
  download - its first request was counted; a client that only ever sends ranges is not), the panel's own paths,
  JSON/HTML, and requests whose user agent says bot/spider/crawl (Caddy leaves them out of the log). Builds,
  installers and CI fetching from the site count like any other download - without an IP or user agent the log
  cannot tell them from a person, and keeping those is the one thing the counter must not do.
- **Privacy**: stored are only `(day, path, count)`. Caddy's access log is filtered before it is written: no IP
  address, no port, no request header (so no user agent, cookie or referrer), no response header. Nothing can be
  tied to a person, so there is nothing to expire or delete on request.
- **Where the data lives**: `downloads.sqlite3` in the admin service's data volume (`admin_data`, `/data`);
  the raw log in the `caddy_logs` volume (10 MiB files, the newest 10, at most 30 days). The path tells the group
  (top folder), the platform (`psc`, `rpi`, `rpi64`, `pcusb`, `windows`), the version and the channel
  (`preview/` and `nightly/` folders; a pre-release version = testing; a plain version = release) - worked out
  when the page is read, not stored.
- **How it runs**: no script in the download path (Caddy serves static files). The admin service reads the log
  every 10 minutes and whenever the tab is opened and the last read is older than 30 s. A read is incremental:
  each log file is told apart by its inode, its offset is saved in the same SQLite transaction as its counts
  (a count is never doubled), a half-written last line waits, and a rotated file is finished before it goes.
  Counting starts when the log is switched on - there is no history before it.
- **Switching it on (the sysadmin, once, on the build server)**: from the site's checkout, after the merge,
  `cd docker/repo && docker compose --profile admin up -d --build` (recreates Caddy with the log and the
  `caddy_logs` volume, and the admin service with the read-only mount). Then download a file from the site and
  open the tab after a minute. If the counts stay empty: `docker compose exec caddy ls -l /var/log/caddy` (is
  there an `access.log`?) and `docker compose logs caddy` (a `log_skip` or `mode` error means a Caddy older
  than 2.8 - `docker compose pull caddy`). The log covers the HTTPS name only, not the plain `:9090` listener.

Tests: `tests/test_downloads.py` (log lines incl. 200/206/304/404/HEAD, rotation, partial lines, the
report's windows, the endpoint's access).
