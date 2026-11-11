# Separate test deployment on mserver

This runbook creates a **new** stack. It does not update `funnelhub-crm`, the Oneshot-CRM checkout, or its volumes. Docker startup/browser/restart tests passed in GitHub CI. The agent could not resolve mserver from this workspace and had no server session, so deployment and production health have not been verified there. Complete one step, confirm it worked, then continue.

Prerequisites: Ubuntu, Git, Python 3, Docker Engine and Docker Compose v2 with `depends_on.condition` and `--wait` support. No GPU is required. Keep the port on loopback until the owner account exists. Use a private SSH tunnel or an authenticated HTTPS reverse proxy for access; native iPhone installation/OAuth callbacks require a suitable HTTPS origin.

## 1. Download the integration branch

```bash
cd ~
git clone --branch integration/funnelhub https://github.com/TE99SJM/FunnelHub-SalesCompel.git
cd ~/FunnelHub-SalesCompel
git remote add upstream https://github.com/occupysaas/salescompel.git
```

Use a fresh directory. If it already exists, inspect it instead of overwriting it.

## 2. Generate the private configuration

```bash
python3 scripts/funnelhub/prepare_env.py
```

This generates new random test credentials and refuses to overwrite `.env`. It does not copy the production encryption key or OAuth connections. The generated values use URL-safe hexadecimal; arbitrary database passwords must be URL-encoded in DSNs. Do not paste `.env`, `docker compose config`, container environment output or database dumps into GitHub.

The default host port is **3051**, bound to `127.0.0.1`. Change `FUNNELHUB_PORT` in `.env` if that port is occupied. `COMPOSE_PROJECT_NAME` must remain distinct from every existing stack. All commands below explicitly use the same test project name.

## 3. Build and start the test stack

```bash
docker compose -p funnelhub-salescompel-test -f compose.test.yml up -d --build --wait --wait-timeout 240
docker compose -p funnelhub-salescompel-test -f compose.test.yml ps -a
curl --fail http://127.0.0.1:3051/api/health
```

Expected: `db` and `app` healthy, `init` exited successfully, and health JSON reports `ok`. `init` runs explicit SalesCompel migrations, creates three restricted runtime logins and the FunnelHub schema, provisions the internal principal, and adds missing Contact fields. Runtime has no database administrator credentials. PostgreSQL uses `en_US.utf8` because upstream legacy schema comparison depends on collation ordering; do not change it on an existing volume.

If initialization fails, inspect only this stack:

```bash
docker compose -p funnelhub-salescompel-test -f compose.test.yml logs --tail=100 init app
```

Do not delete a volume to clear an error without first determining whether it contains data you need.

## 4. Open the app and create the owner

From a computer that can SSH to mserver:

```bash
ssh -L 3051:127.0.0.1:3051 samuel@mserver
```

Then open `http://localhost:3051` on that computer and create the owner account. The SSH hostname may be replaced with the server's established private address. Keep this tunnel open while testing.

After setup, an operator can set `FUNNELHUB_BIND` to the server's verified Tailscale/LAN address for private phone access and recreate only `app`:

```bash
docker compose -p funnelhub-salescompel-test -f compose.test.yml up -d app
```

Use HTTPS for regular use. No public proxy or DNS changes have been made by this integration. Do not expose PostgreSQL or the Go engine port. The Go engine remains bound to container loopback.

## 5. Test with synthetic records

Create/edit an Account and a Contact with a company. Open CRM, use **Sync contacts**, and check the company link. Upload a photo/video in Compose using the visible file input, save a draft, refresh, reopen it, and verify Media Library. Restart only this stack's app and verify the records and files remain:

```bash
docker compose -p funnelhub-salescompel-test -f compose.test.yml restart app
docker compose -p funnelhub-salescompel-test -f compose.test.yml ps
```

The automated destructive-to-fixtures acceptance script is only for a **new, empty disposable** stack; it refuses an initialized application. See TESTING.md. Do not run it against your manually configured test workspace.

## 6. Connect services deliberately

The original Integration forms and callback paths are retained. Use fresh sandbox or test connections first. Gmail currently uses IMAP with an app password. Square imports remote data only; its POST is the read-only order-search endpoint. Do not enable notifications or publication while rehearsing copied data.

- `SYNC_SCHEDULER=false`: periodic external polling is off. Manual authorized read tests still work.
- `EXTERNAL_PUBLISH_ENABLED=false`: immediate publishing, retries and due-job execution are blocked.
- `PUBLIC_MEDIA_ENABLED=false`: unauthenticated capability URLs are blocked; authenticated downloads still work.

Enable external publication only after verifying exact test destinations and scopes. Instagram/TikTok media fetching may require public HTTPS media delivery. Public links use unguessable tokens and grant access to anyone holding the URL; do not enable them for confidential files. No platform permission, app review or unsupported capability is bypassed.

## Updates, rollback and Portainer

For later source updates, inspect the integration PR and migration notes first, then:

```bash
cd ~/FunnelHub-SalesCompel
git pull --ff-only origin integration/funnelhub
docker compose -p funnelhub-salescompel-test -f compose.test.yml up -d --build --wait
```

Stopping just the test stack leaves its volumes intact:

```bash
docker compose -p funnelhub-salescompel-test -f compose.test.yml down
```

Do not add `-v` for a workspace whose data you want to retain. A source rollback does not roll back a migrated database. Preserve a private database dump and the encryption key/media before upgrading non-disposable data; GitHub is source versioning, not a database backup.

For Portainer, use a **Git repository stack** pointing to this repository, ref `refs/heads/integration/funnelhub`, Compose path `compose.test.yml`, stack/project name `funnelhub-salescompel-test`. Supply the generated `.env` values through Portainer's environment mechanism. A pasted stack without the checked-out Docker build context is insufficient. This Portainer path has not been exercised. Alternatively manage the CLI-created stack's containers in Portainer.
