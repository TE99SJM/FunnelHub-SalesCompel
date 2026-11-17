# Migration assessment and offline rehearsal — no production import performed

## Source and target

The inspected FunnelHub revision uses SQLite at `/data/funnelhub.db`, its generated encryption/signing key at `/data/.secret_key` unless SECRET_KEY is supplied, and uploaded files under `/data/media`. Its Compose file names the volume `crm-data` and container `funnelhub-crm`. A previous inventory reported `oneshot-crm_crm-data`; the current mounts, schema, revision and key source must be verified on mserver. The server was unreachable from the development workspace; no production inventory or data was accessed.

The application uses one PostgreSQL database: SalesCompel in `public`, marketing data in `funnelhub`. The version 1 offline importer **only creates a new `fh_rehearsal_*` schema**. It cannot import into `public` or `funnelhub`, overwrite a schema, activate providers, or cut over the running application. The supplied Compose stack never points to the rehearsal schema automatically.

| Source | Version 1 behavior |
|---|---|
| Users/password hashes | Retain hashes and integer IDs. Target application signing key must be independent, invalidating old sessions. |
| Contacts | Retain IDs and all fields; email duplicates are reported, never merged by name/email. Generate stable UUID mappings with CRM projection held for review. |
| Funnels/stages/deals/activities | Preserve IDs, foreign keys, timestamps, dates, booleans and relationships. No fictitious SalesCompel Opportunity conversion. |
| Channels/integrations | Retain provider IDs, config, sync intervals and history; set every integration disabled. Interrupted syncs get an explicit review message. |
| Orders/emails/messages/metrics | Preserve stored data and relationship IDs. Reject duplicate nonempty provider identities, channel/metric keys and metric/day keys instead of silently discarding records. |
| Media | Copy only referenced originals and JPEG derivatives into a new directory; verify size/SHA-256, reject missing files, path traversal and symlinks. Private file modes; rotate public media tokens. |
| Scheduled posts/jobs/targets | Scheduled planner posts become drafts; queued/in-progress jobs and targets become canceled. Original held statuses remain in a private journal. Review remote status before creating another publication. Historical completed rows are retained. |
| Composer drafts | Preserve text, media and integration IDs; verify JSON references. Older source versions without this table remain supported. |
| Notifications | Disable the master switch and all delivery channels while retaining other config/history. |
| OAuth/integration credentials | Default: omit encrypted secrets and reconnect. Optional: decrypt in memory with original key, re-encrypt with target key using the existing FunnelHub cipher, discard transient OAuth state. No provider refresh/validation occurs. |

Unknown tables/columns, non-additive schema changes, broken foreign keys, invalid types and ambiguous provider identities stop import. Known legacy additive columns receive their existing model defaults. The source must be a standalone, consistent SQLite snapshot without WAL/SHM/journal sidecars. The importer opens it read-only/immutable, checks its hash again before commit, and never runs source startup migrations.

## Prepare a private rehearsal

1. Obtain authorization and inventory production read-only. Record exact image/revision, mounts, DB location, key source, media size and callback URLs without printing credentials.
2. Export one consistent SQLite snapshot with SQLite's backup API. Do not copy a live WAL database file alone. Production export/maintenance is not performed by this tool. Preserve the original key separately in private storage. Avoid duplicating large media libraries just to inspect them.
3. Install the pinned backend requirements in a private virtual environment on the isolated rehearsal host:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r modules/funnelhub/backend/requirements.lock
   ```

4. Assess the exported snapshot. The source-media directory is read-only input and can be an operator-provided read-only mount:

   ```bash
   .venv/bin/python scripts/funnelhub/import_legacy.py assess \
     --snapshot /private/export/funnelhub.db \
     --source-media /private/export/media
   ```

   Output contains counts, aggregate media bytes, source hash and duplicate-email group count, not customer rows, tokens or file names. The original simpler `assess_legacy.py` remains available for inventory before strict validation.

5. Prepare a **disposable PostgreSQL test database** and a separate empty parent directory for media. A private `0600` file `/private/rehearsal/target-dsn` must contain a SQLAlchemy URL using `postgresql+psycopg://...`. Use an account with schema-creation permission in that test database; no production DSN. Enter this privately, never in shell history or GitHub. The application runtime keeps its existing restricted roles. The destination schema and media directory below must not already exist.

   ```bash
   .venv/bin/python scripts/funnelhub/import_legacy.py apply \
     --snapshot /private/export/funnelhub.db \
     --source-media /private/export/media \
     --dsn-file /private/rehearsal/target-dsn \
     --schema fh_rehearsal_first \
     --target-media /private/rehearsal/imported-media \
     --disposable-target
   ```

   Save the returned `run_id`. All IDs/relationships are inserted in dependency order in one PostgreSQL transaction. Sequences advance beyond imported IDs. Counts are reconciled; per-table content hashes and media hashes are journaled privately. PostgreSQL schema translation uses the existing SQLAlchemy model metadata rather than duplicating DDL.

6. To rehearse credential preservation, add **both** `--source-key-file /private/export/source-key` and `--target-key-file /private/rehearsal/target-key` to the apply command. Both must be regular private `0600` files containing only the effective key. The target key must match the future target application's SECRET_KEY. Wrong keys fail before writing the target. Never put key files, DSNs, snapshots, media or journals in GitHub. Re-encryption establishes decryptability only; real grants/callbacks/token validity remain unverified.

7. Reconcile a completed import using its returned run ID:

   ```bash
   .venv/bin/python scripts/funnelhub/import_legacy.py verify \
     --dsn-file /private/rehearsal/target-dsn \
     --schema fh_rehearsal_first \
     --target-media /private/rehearsal/imported-media \
     --run-id REPLACE_WITH_RETURNED_RUN_ID
   ```

   Verification checks all table counts/content hashes and each media file. Applying again to the same target is refused; verify the existing run instead. No append or merge path can create duplicates on retry.

## Rollback and interrupted imports

For a completed, unchanged rehearsal only:

```bash
.venv/bin/python scripts/funnelhub/import_legacy.py rollback \
  --dsn-file /private/rehearsal/target-dsn \
  --schema fh_rehearsal_first \
  --target-media /private/rehearsal/imported-media \
  --run-id REPLACE_WITH_RETURNED_RUN_ID \
  --disposable-target
```

Rollback verifies the run marker, every table and file, then removes only that rehearsal's tables/schema and recorded media. It refuses changed rows, added tables/columns/files, wrong IDs and production schema names. SQL drops use RESTRICT, never CASCADE into external dependencies. Do not attach an application or other schema to a rehearsal being rolled back.

Database creation/data insertion is transactional; files and PostgreSQL cannot commit atomically. If import fails or the connection is lost during commit, **keep the private staging directory**. Its `0600` `.funnelhub-import.json` records the run ID, source fingerprint and expected media. If the schema committed, use `verify`; if it is absent, the schema transaction rolled back. Partial media is deliberately not deleted automatically. An operator must reconcile an uncertain outcome and remove only the confirmed orphan directory before retry. Similarly, interrupted post-commit rollback file cleanup requires private inspection. No force-delete or automatic production restore is offered.

The journal and stable IDs make reconciliation repeatable. This is not a database backup service. Before cutover, rehearse PostgreSQL backup/restore together with the correct encryption key and media; GitHub holds source only. Existing FunnelHub remains the rollback path throughout isolated testing.

## Remaining cutover gates

- Rehearse against an authorized real snapshot and resolve all duplicate identities/unknown schema differences.
- Verify target account roles, callbacks and grants using sandbox/test accounts; never test by modifying live Square inventory/orders/settings.
- Review held publication state remotely; decide which installation exclusively owns polling/publication.
- Reconcile company identities before enabling CRM projections. Queue entries are held (`pending=false`); activation/promotion into the application schema is intentionally not automated.
- Add a reviewed promotion/activation procedure and full backup/restore rehearsal. Only explicit authorization can permit production cutover.
- Version 1 materializes database rows for validation; very large email/history datasets need a measured memory budget and streaming import before production use. Unknown source schemas fail closed.

Synthetic PostgreSQL import, sequence, relationship, media, re-encryption, reconciliation and rollback checks are included in `tests/test_legacy_import.py`. They do not prove production migration readiness.
