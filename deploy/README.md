# Deploying AutoSkill

Two paths, and they do not mix: systemd on a bare server, or two containers on k3s.
The container path is the one skills.tadamoo.com runs on - see the end of this file.

## On a bare server, under systemd

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

## LLM providers of the server

The models AutoSkill calls are configured from *Administration → AI providers*, and that panel is
the only source of the choice — local engines, API keys, subscriptions reused from an official CLI.
It needs the `llmswitch` library in the same virtualenv; it is installed separately because it is
not on a public index, but without it no generative step can run:

```bash
sudo /opt/autoskill/venv/bin/pip install <llmswitch repository or path>
sudo -u autoskill mkdir -p /var/lib/autoskill
echo 'AUTOSKILL_LLMSWITCH_REGISTRY=/var/lib/autoskill/llm_providers.json' | sudo tee -a /opt/autoskill/autoskill.env
sudo systemctl restart autoskill-api autoskill-worker
```

That file holds API keys, so it must be owned by the `autoskill` user and readable only by it; it is
deliberately outside `/opt/autoskill/app`, which `install.sh` overwrites on every update. Without the
library the panel says so and every interview, draft and coach reply answers `no_llm_provider`.

On a server with a GPU, `AUTOSKILL_LLMSWITCH_LOAD_MODELS=0` stops a background job from loading a
model on its own initiative: a local engine is then used only for what is already in memory. See
[`docs/llm-providers.md`](../docs/llm-providers.md).

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


## On k3s, in containers

What runs at <https://skills.tadamoo.com>. Two images - `autoskill/api` (the FastAPI application on a
virtualenv that also carries `llmswitch`) and `autoskill/web` (the built SPA behind an nginx that
forwards `/api/`, `/dl/` and `/git/` to the API). The web image is the only front door: the reverse
proxy outside the cluster has one upstream to point at, not two.

```bash
# On the node. AutoSkill's sources arrive however you like - `git archive HEAD` over ssh is enough.
# llmswitch does NOT: send its working tree, `tar --exclude=.git`. Half of what the provider panel
# calls lives in files that are not committed, and an image built from its HEAD starts, serves
# every other page, and answers the provider panel with `has no attribute 'panoramica'`.
bash deploy/docker/build.sh --llmswitch /opt/build/llmswitch

kubectl create namespace autoskill
kubectl -n autoskill create secret generic autoskill-secrets \
    --from-literal=secret-key="$(openssl rand -base64 48 | tr -d '\n')"
kubectl apply -f deploy/k8s/configmap.yaml -f deploy/k8s/autoskill.yaml
kubectl -n autoskill rollout status deploy/autoskill-api deploy/autoskill-web
```

`build.sh` ends by piping both images through `docker save` into `ctr -n k8s.io images import`: k3s
runs containerd, so an image built by docker is invisible to the cluster until it is handed over.
This is why both deployments carry `imagePullPolicy: IfNotPresent` - there is no registry to pull
from, and `Always` would make every pod fail on `ErrImagePull`. Build on the node, or push to a
registry and change the two image references.

The build is long (`npm ci` alone takes minutes) and dies with the ssh session that started it, so
start it detached:

```bash
ssh root@node 'cd /opt/build/autoskill && setsid nohup bash deploy/docker/build.sh \
    --llmswitch /opt/build/llmswitch > /opt/build/autoskill-build.log 2>&1 < /dev/null &'
```

A workstation usually builds this faster than the node does. Build there and hand the result over:
the import runs on the node either way, and it is the slow half - five to nine minutes for the API
image.

```bash
bash deploy/docker/build.sh --no-import        # llmswitch defaults to ../llmswitch
for image in api web; do
    docker save "docker.io/autoskill/$image:latest" \
        | ssh root@node 'k3s ctr -n k8s.io images import -'
done
```

### The public hostname

`autoskill-web` is a NodePort on **30890**, because the reverse proxy in front of this cluster
(Nginx Proxy Manager) runs on the host network and reaches every other site the same way. The
proxy host is `skills.tadamoo.com` -> `http://<node address>:30890`, with websockets enabled -
the interview and the job log are server-sent events, and `proxy_buffering off` is already set
inside the web image. Let's Encrypt issues the certificate from the same panel.

DNS is one A record, `skills` -> the node address, at the registrar.

Three settings in `configmap.yaml` depend on that hostname and have to move with it:
`AUTOSKILL_PUBLIC_URL` (embedded in every install bundle), `AUTOSKILL_CORS_ORIGINS`, and
`AUTOSKILL_COOKIE_SECURE`.

### State

One replica, on purpose: `AUTOSKILL_JOBS=inline` and `AUTOSKILL_EVENTS=memory` are correct for one
process and wrong for two. Everything that must survive a redeploy is on the `autoskill-data` PVC
mounted at `/data` - the SQLite database, the content store, and `llm_providers.json` with the
provider API keys. The API keys are therefore never in an image layer. Growing past one replica
means Postgres and Redis, both already in this cluster; see the table above.

The first account registered through the web UI becomes the administrator, who can then close
registration from the admin area.
