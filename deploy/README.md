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
the code, rebuilds the frontend and applies migrations. Put HTTPS termination in nginx (certbot) and set
`AUTOSKILL_COOKIE_SECURE=true` once the site is served over HTTPS.
