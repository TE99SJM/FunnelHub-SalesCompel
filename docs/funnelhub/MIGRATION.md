# Migration assessment — no production import performed

## Source and target

The inspected FunnelHub source defaults to SQLite at `/data/funnelhub.db`, stores its generated encryption/signing key at `/data/.secret_key` unless SECRET_KEY is supplied, and stores uploaded files under `/data/media`. Its Compose file names the volume `crm-data` and container `funnelhub-crm`. A previous server inventory reported `oneshot-crm_crm-data`; **the actual current volume, schema and configuration must be verified on mserver** before migration. No production inventory was accessed during this work.

The new stack uses one PostgreSQL database: SalesCompel in `public` and marketing data in `funnelhub`. Media lives in a different test-only persistent volume. Nothing mounts or changes the production volume.

| Source | Destination / rule |
|---|---|
| Users/password hashes | Existing hash format can be retained; initial test owner is separate. Session signing key changes invalidate old sessions. No automatic production account import exists. |
| Contacts | Preserve integer IDs in `funnelhub.contacts` so existing email/deal/order links survive; create durable `crm_projections` and SalesCompel Contact IDs. |
| Company strings | Stable normalized company key maps to a SalesCompel Account. Company-name normalization is an initial heuristic, not verified legal entity identity. Review collisions and spelling variants before import. |
| Funnels/stages/deals/activities | Preserve primary and foreign keys in the marketing schema. They are not falsely converted to a nonexistent SalesCompel Opportunity model. |
| Channels/integrations | Preserve channel IDs, provider IDs, config and encrypted secrets only after a key-handling rehearsal. Disable each imported integration and all schedulers initially. |
| Orders/emails/messages/stats | Preserve provider IDs, timestamps and relationship IDs; reconcile counts and per-source duplicates. |
| Media metadata/files | Copy stored originals and JPEG derivatives together into the new media volume; verify each file's size/hash privately. Keep the old originals untouched. |
| Publishing jobs | Import history. Hold pending jobs; interrupted posting requires remote-status review before retry to avoid duplicate public posts. |
| OAuth tokens | Decrypt using the original key in a private offline process, re-encrypt with the target key, never print plaintext. Refresh tokens may require reconnecting or callback changes. This transformation is not implemented or executed. |

## Safe rehearsal sequence

1. Read-only inventory: exact image/revision, volume mounts, database path, effective secret-key source, media bytes and OAuth callback URLs. Do not log environment values.
2. Produce one consistent SQLite snapshot using SQLite's backup API, or a controlled maintenance window; a raw copy of only `funnelhub.db` while WAL writers run is unsafe. This requires explicit authorization for the production operation. Do not create large media duplicates merely to inspect the schema.
3. Run the included read-only assessment on the **exported snapshot**, not a live production mount:

   ```bash
   python3 scripts/funnelhub/assess_legacy.py /private/export/funnelhub.db --media-dir /private/export/media
   ```

   It reports table counts, duplicate nonempty email groups, foreign-key violations, encrypted connection counts and missing/unsafe media paths. It never exports row content or credentials and has no write mode.
4. Build and review a versioned importer: preserve IDs, map types, reset PostgreSQL sequences, journal source-to-target IDs, reconcile counts, preserve timestamps and deduplicate provider `(source, external_id)` keys. Quarantine ambiguous identities; do not merge people simply because names match. This importer remains a release gate.
5. Import into a fresh target with sync/publication/notifications off. Re-encrypt credentials privately, or reconnect services. Validate contact projections without importing duplicate CRM identities.
6. Reconcile every table and relationship; sample Gmail links, Square order/customer links, historical metrics, media bytes and scheduled-job holds. Test restart and restore. Inspect any mismatches before cutover.
7. Only after explicit approval, schedule cutover and decide which instance owns polling and publication. Never run two schedulers against migrated pending jobs.

## Idempotency and rollback

The new contact projection commits its queue entry in the same database transaction as a contact change, retains a UUID source key and recovers an already-created remote CRM record before retry. PostgreSQL row locks serialize queue processing. Duplicate source-key matches stop with a visible reconciliation error. Account upserts use SalesCompel's unique external key. This protects new projection writes; it is not a complete production migration tool.

Existing production remains the rollback path during rehearsal. Stop the test stack without deleting its volumes. A completed SalesCompel schema upgrade is forward-only: database rollback requires restoring the pre-upgrade snapshot together with the correct encryption key and media. Keep those privately, with retention proportional to actual risk. GitHub contains source only and cannot restore database records or OAuth tokens.
