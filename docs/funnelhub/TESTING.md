# Test results — 2026-11-11

## Executed checks

| Check | Result | Boundary |
|---|---|---|
| Original FunnelHub backend suite | 69 passed | External APIs/IMAP mocked; optional SOCKS dependency added to this environment |
| Integrated FunnelHub suite | 83 passed on SQLite and again on PostgreSQL | Adds auth, contact queue/recovery/conflict/rollback, drafts, media cleanup/limits/private delivery, publication gate and redaction tests |
| Original SalesCompel Go suite | 572 passed, 0 failed, 0 skipped | Real disposable PostgreSQL 17.11; separate restricted record/identity roles |
| Original SalesCompel Vue build + units | Build passed; 5 tests passed | Original Vue source unchanged |
| Unified React build | TypeScript and Vite passed | Browser behavior tested separately in CI |
| New initializer | Fresh initialization and repeat initialization passed | Actual Go migration/provision/schema CLI and PostgreSQL |
| Integrated API smoke | Passed | One owner login; account create/edit; contact create/edit; durable projection and company Account link; no duplicate repeat sync |
| Persistent media and drafts | Passed | Multipart PNG, private authenticated download, draft save/reload, disabled publication |
| Process restart | Passed | Restarted both Go/Python; login, account/contact, draft and original media bytes survived |
| Empty provider/analytics states | Passed | Actual empty database, no fabricated connected accounts/metrics |
| Python compilation | Passed | App, deployment and assessment scripts |
| Docker image + Compose startup | Passed in GitHub CI | Separate disposable PostgreSQL/media volumes; health checks passed |
| Desktop Chromium + iPhone-sized WebKit | Passed in GitHub CI | Login, navigation, account creation, native filechooser event, upload, draft reload; physical iPhone untested |
| Docker app/database restart | Passed in GitHub CI | Login, CRM records, draft and original media bytes survived |
| Offline migration assessor | Passed on synthetic SQLite snapshot | File hash unchanged; duplicates, missing/unsafe media paths detected; no row/secret export |

The PostgreSQL baseline initially failed under locale C because upstream compares sorted constraint definitions against a locale-dependent fixture. The integration uses `en_US.utf8`, which passed all 572 tests, without editing frozen upstream migrations. A real adapter probe also exposed that upstream external-ID routes support PATCH, not GET; the adapter now takes the ID from PATCH's verified response.

Sanitized acceptance summaries are in `docs/funnelhub/evidence/`. No raw credentials, OAuth tokens, production customer records or database dumps are included.

## Verification boundaries

- Local browser execution was blocked by Unix-domain socket restrictions. GitHub CI subsequently passed Chromium and WebKit/iPhone emulation. Physical iPhone remains separate.
- Docker is unavailable locally; image build, Compose lifecycle and restart were exercised successfully in GitHub CI. Portainer and the actual server remain unverified. Inspect the PR's latest result before merging.
- All live social/Gmail/Square/GA4 operations: no credentials or sandbox accounts were supplied. Reused mocked tests prove response handling only.
- mserver deployment, old-container health and actual legacy migration: no server session or production volumes were accessed. The original repository and installation were not changed.
- Salesforce reference-org certification was not run. Offline compatibility CI initially reached 456 passes, one failure and six skips: its inherited workflow used Go 1.24 against a Go 1.25 fixture. The workflow now selects Go from go.mod; inspect its rerun. Local offline tests also encountered proxy/PATH/Unix-socket limitations; correcting proxy/PATH recovered eight failures. These are not live Salesforce parity results.

## Reproduce local API/database tests

From repository root, with Python 3.12, Go 1.25 and PostgreSQL 17 installed:

```bash
python3 -m venv .venv
.venv/bin/pip install -r modules/funnelhub/backend/requirements.lock
cd modules/funnelhub/backend
../../../.venv/bin/python -m pytest -q
cd ../../..
npm ci --prefix modules/funnelhub/frontend --ignore-scripts
npm run build --prefix modules/funnelhub/frontend
go build -o /tmp/funnelhub-salescompel ./cmd/salescompel
.venv/bin/python scripts/funnelhub/acceptance_local.py \
  --postgres-bin /usr/lib/postgresql/17/bin \
  --salescompel-bin /tmp/funnelhub-salescompel \
  --go-bin "$(command -v go)" \
  --provider-suite \
  --out /tmp/funnelhub-acceptance.json
```

Run as a non-root user with the `en_US.UTF-8` locale installed. The harness creates a temporary PostgreSQL cluster with synthetic records, no external provider credentials, and shuts down/removes only that cluster. It does not target a running database. It requires socket/process capabilities absent in some restricted environments.

## Docker and browser gates

The `FunnelHub isolated integration` workflow builds `compose.test.yml`, initializes a separate disposable database, runs mocked provider tests, exercises Chromium and WebKit with an iPhone viewport, checks file-chooser events and draft reload, then restarts app/database and checks persistence. It removes only that CI runner's disposable stack. No repository secrets are needed. Its result is not presumed from the existence of the workflow.

For an explicitly disposable, newly built empty local stack only:

```bash
node web/node_modules/playwright/cli.js install --with-deps chromium webkit
.venv/bin/python scripts/funnelhub/acceptance_stack.py \
  --disposable-test-stack \
  --browser-script scripts/funnelhub/browser_acceptance.cjs \
  --restart --out /tmp/funnelhub-results/stack.json
```

This script refuses an application with an existing owner. It creates synthetic accounts/contacts/media/drafts and requires publishing/public media to be off. Do not use it for an established workspace.

## Inherited CI dependency repair

The first fork CI run reproduced `EBADPLATFORM` before the upstream compatibility checks: the locked nested `@unrs/resolver-binding-linux-x64-musl` package lacked its optional flag. Both GNU and musl variants are declared optional by their parent `unrs-resolver`; the lockfile now records that metadata for both. Versions and integrity hashes are unchanged. `npm ci --ignore-scripts` passed locally after the two-line correction. This change affects compatibility-lab installation only, not the Go engine or application runtime.

## First Docker/browser CI result

[Initial isolated CI run](https://github.com/TE99SJM/FunnelHub-SalesCompel/actions/runs/43118076524) passed the 83 backend tests, image build, healthy Compose startup, CRM/account/contact checks, media/draft API checks and the complete Chromium desktop browser test. The WebKit iPhone test reached account creation but timed out finding the table cell; responsive `display` rules can remove implicit table accessibility semantics in WebKit. CRM table roles are now explicit and the browser test checks the account-create HTTP result and retains failure evidence. The rerun must pass before mobile/browser/restart acceptance is reported as complete.

## Verified CI evidence

[Passing isolated Docker/browser/restart run](https://github.com/TE99SJM/FunnelHub-SalesCompel/actions/runs/43118870378), application revision `087ed5b4dae4c0a76fdcfb8ceeee4c9e80f7a374`, passed all workflow steps. Sanitized `stack.json` and `browser-acceptance.json` are retained under evidence. This supersedes the initial WebKit table-lookup failure above. The result verifies browser emulation and synthetic operations, not real device or provider authorization.

Screenshot review then identified additional composer horizontal overflow beyond the original navigation-width coverage. The layout now bounds native select/file controls and uses shrinkable grid columns, and the browser suite explicitly checks composer width before upload and after saved-draft reload. Consult the latest integration workflow result for these additional assertions.

The optional `--provider-suite` local harness runs all 83 mocked provider/backend tests in its newly created PostgreSQL marketing schema before starting the application, then clears only that disposable schema. Do not set `FUNNELHUB_TEST_DATABASE_URL` to any database whose data you want to keep. The default unit suite still uses a fresh temporary SQLite database.
