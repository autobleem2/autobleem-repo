# The admin panel

`https://autobleem.retromenele.pl/admin/` - what the builders are doing, what each channel holds, the build
server's health, and the release team's buttons (a nightly, a promotion, cancel / re-run, withdraw, republish
the page). The plan and the reasons: `autobleem-main`'s `docs/admin-panel-plan.md`.

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

## For scripts and Claude sessions

The same API with your own GitHub token as the bearer - the same rules as the browser, recorded in the audit
log as `via api`:

```
curl -H "Authorization: Bearer $(gh auth token)" https://autobleem.retromenele.pl/admin/api/status
curl -H "Authorization: Bearer $(gh auth token)" -H "Content-Type: application/json" \
     -d '{"platforms":["psc"],"dry_run":true}' https://autobleem.retromenele.pl/admin/api/nightly
```

`GET` `me`, `status`, `channels`, `health`, `audit`, `promote/preview?kind=alpha&version=` ; `POST` `nightly`,
`promote`, `runs/<repo>/<id>/cancel`, `runs/<repo>/<id>/rerun`, `withdraw`, `page`. A browser's `POST` also
needs the header `X-AB-Request: 1` (the page sends it; a cross-site form cannot).
