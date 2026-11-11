# FunnelHub integration decision — 2026-11-11

## Inspected sources

- SalesCompel `2ff665dfa56ae606154f6eb260b795559f8bd680` (Apache-2.0).
- Oneshot-CRM `16f9a9f` (full revision recorded in `modules/funnelhub/PROVENANCE.md`).
- No production database, Docker volume, server session or provider credentials were accessed.

## Findings before implementation

SalesCompel is a Go 1.25/PostgreSQL CRM candidate, not a complete Salesforce replacement. Its persistent API supports Account/Contact CRUD, a limited query language, Account external-ID upsert, atomic Composite writes, additive Text custom fields/objects, tenant RLS and OAuth. Its Vue connected editor uses these APIs. Its separate polished preview uses synthetic in-memory records. Sales pipeline, reporting and automation are not complete CRM products.

FunnelHub is FastAPI/SQLAlchemy with a React/Vite interface. It defaults to SQLite at `DATA_DIR/funnelhub.db`; SQLAlchemy permits PostgreSQL. PBKDF2 passwords and bearer JWTs protect one shared business workspace. Fernet encrypts integration secrets using a key derived from SECRET_KEY. Media is under `DATA_DIR/media`. Scheduled sync/publishing runs in the API process, so use one worker. It has real provider implementations, not proof of live authorization. The source test suite passed 69 tests with mocked external services. The frontend compiled. These are not live provider acceptance tests.

Gmail is IMAP ingestion with an app password, contact linking and an email viewer; it is not Gmail OAuth or a send/reply API. Twitch retrieves channel/stream data; it is not a publishing destination. Square retrieves customers, orders/payments and catalog counts; no inventory editor exists. GA4 reports require a property, hostname and service-account access, not a built-in tracking pixel.

## Chosen architecture

Preserve SalesCompel's source layout and Go engine. Place the reused FunnelHub source in `modules/funnelhub`, with provenance and local changes documented. Keep the existing React workflows as the unified shell, and call the original SalesCompel REST API through an authenticated Python adapter. Avoid rewriting all Python providers in Go or mixing Vue and React runtimes in one page.

Use one PostgreSQL server and one database: SalesCompel in `public`, FunnelHub in an isolated `funnelhub` schema. Separate logins preserve SalesCompel's record/identity permissions. The Python role owns only its own schema. A one-shot initialization container has migration privileges; runtime processes do not. The app container supervises the existing Go process on loopback and one Python worker. Only Python's application port is exposed. A persistent media volume is separate from the PostgreSQL volume.

The initial test edition is a single-owner business workspace. FunnelHub login authorizes the adapter; the adapter's provisioned SalesCompel service principal stays server-side. This gives one application login, not per-user Salesforce OAuth federation. Do not market this as a multi-tenant SaaS identity design. Direct untrusted access to the internal Go port is not supported.

## Shared records and bounded consistency

Preserve legacy integer contact IDs and their email/deal/order relationships. A durable projection queue maps those contacts to SalesCompel Contact IDs and companies to Accounts. Contact edits and integration imports remain owned by FunnelHub; SalesCompel contains their core CRM projection. Use a stable source key and recover an already-created record before retrying after a crash. Show synchronization errors and retry explicitly. The application does not expose a second editor for projected contacts. Native accounts remain editable through the SalesCompel API. This is eventual consistency, not an atomic distributed transaction. Bidirectional arbitrary external edits and production reconciliation remain acceptance gates.

## Safety and compatibility

The test stack has a unique Compose project, volumes and configurable port. It never mounts the old production volume. External publishing and automatic provider synchronization default off. Real account testing requires deliberate configuration; no production credentials are included. Preserve original OAuth setup paths and redirect configuration, but never assume tokens can be moved without their encryption key and provider redirect updates.

SalesCompel's Apache license and notices are retained. FunnelHub has no declared source license at the inspected revision. The repository owner's explicit instruction authorizes this integration; it does not establish a blanket redistribution license. Reused modules are not silently relicensed as Apache. Package licenses and pinned dependency inventory must be reviewed before public release. This fork adds no proprietary Salesforce source or copied Salesforce UI.

## Alternatives rejected

- Rewrite providers in Go: unnecessary functionality loss and API regression risk.
- Mount the existing SQLite volume: would modify production and share job execution.
- Two independent apps/databases with separate logins: duplicates identity and customer records.
- Expose a shared privileged CRM token in browser storage: leaks server authority.

## Release gate

Keep the integration PR in draft until PostgreSQL/runtime/browser tests, Docker build/restart, real mobile picker, provider sandboxes, migration rehearsal and server isolation checks pass. Tests skipped for environmental reasons are not passes.
