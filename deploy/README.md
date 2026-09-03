# Deploying AutoSkill on a server (no Docker)

Requirements: Linux with systemd, Python 3.11+, Node 20+ (only to build the frontend), nginx.
Optional for the multi-process mode: PostgreSQL 14+ and Redis 6+.

```bash
git clone <this repo> && cd AutoSkill
sudo ./deploy/install.sh /opt/autoskill      # installs into /opt/autoskill, creates the `autoskill` user
sudo nano /opt/autoskill/autoskill.env       # set AUTOSKILL_PUBLIC_URL, CORS origins, database
sudo systemctl restart autoskill-api
sudo cp deploy/nginx.conf /etc/nginx/sites-available/autoskill && sudo ln -s /etc/nginx/sites-available/autoskill /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Two run modes, chosen in `autoskill.env`:

| Mode | Database | Jobs / events | Services |
|---|---|---|---|
| single-process (default) | SQLite or Postgres | `AUTOSKILL_JOBS=inline`, `AUTOSKILL_EVENTS=memory` | `autoskill-api` only |
| with worker | Postgres | `AUTOSKILL_JOBS=arq`, `AUTOSKILL_EVENTS=redis`, `AUTOSKILL_REDIS_URL` | `autoskill-api` + `autoskill-worker` |

The first account registered through the web UI becomes the administrator. Re-running `install.sh` updates
the code, rebuilds the frontend and applies migrations.

## HTTPS and download links

`deploy/nginx.conf` serves the site over HTTPS (certificates from certbot) and redirects HTTP. Agents fetch
install bundles from `/dl/<token>/...`: the token in the path is the only authorization, so the site must
run over HTTPS, `/dl/` and `/git/` are kept out of the access log, and `AUTOSKILL_PUBLIC_URL` must be the
public `https://` address (it is embedded in every bundle). Set `AUTOSKILL_COOKIE_SECURE=true` as well.

Admin settings (web UI) that bound the download surface: `download_rate_per_minute` (per token / IP,
shared across API workers when `AUTOSKILL_EVENTS=redis`) and `max_active_download_links_per_user`.

## Smoke test

`./deploy/smoke.sh` installs into a temporary prefix without systemd or nginx, starts the API, checks
`/api/v1/health`, the migrations and that the `autoskill-local` wheel is served at
`/dl/autoskill-local/latest`. CI runs it on every push.

## Email

Invitations, password resets and the notifications a person opted into by email go through
`AUTOSKILL_EMAIL_BACKEND`: `console` (default: logged, nothing sent), `smtp` (`AUTOSKILL_SMTP_HOST`,
`AUTOSKILL_SMTP_PORT`, `AUTOSKILL_SMTP_USERNAME`, `AUTOSKILL_SMTP_PASSWORD`, `AUTOSKILL_SMTP_STARTTLS`,
`AUTOSKILL_EMAIL_FROM`) or `none`. Messages are sent in the recipient's language (en, it, de, es, fr, hu).
With registration closed (admin setting), new people join through invitations sent from Admin → Users.
