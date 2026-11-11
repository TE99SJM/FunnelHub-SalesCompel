# Known issues and next priorities

## Release blockers

1. Run the Docker/browser workflow and verify its result. This workspace cannot launch browsers because Unix-domain socket creation is denied; Docker is unavailable here. Source builds and real non-Docker PostgreSQL/runtime tests pass, but they do not prove Docker build/restart or UI behavior.
2. Test the separate stack on mserver and on a physical iPhone. Verify owner setup, native Files/Photos selection, large MOV uploads, touch layout, restart and no interference with the existing container. A browser-emulated iPhone is not a physical-device test.
3. Reconnect sandbox/test providers and verify actual grants. Existing tests mock external API/IMAP responses. YouTube/TikTok/Meta app reviews, scopes, quota, account eligibility and OAuth redirect correctness remain unverified. No live Gmail or Square account was accessed.
4. Rehearse a versioned production importer and reconciliation/restore procedure. Only a read-only assessment tool exists. No production token/data migration is complete.
5. Confirm redistribution licensing for owner-supplied FunnelHub source. No source license exists at the inspected revision. Owner-authorized reuse is recorded; a general redistribution grant is not invented.

## Functional limits

- Single business workspace: one owner login gates the CRM service principal. Per-user SalesCompel OAuth federation, roles and tenant selection are not implemented. Do not expose this as multi-tenant SaaS.
- Contacts are a durable, eventually consistent projection. FunnelHub owns edits; arbitrary edits made directly against SalesCompel are not merged back. The UI deliberately presents projected contacts read-only in CRM. Native Account names created from companies may be refreshed by later contact projection. Reconciliation/conflict UI, per-record backoff and larger-scale queue fairness are future work.
- The upstream Account note/external-key fields are limited to 80 characters. CRM lists are bounded at 2,000 rows; the media library returns the latest 500 items. Full pagination remains planned.
- Gmail is an IMAP viewer/importer with contact links, not Gmail OAuth, send/reply or provider-side mailbox management.
- Square supports remote reads, local customer/order/deal import, payment detail and catalog counts. Full product/inventory screens and remote writes are not implemented.
- GA4 supplies per-site real metrics/history; dedicated referral and traffic-source breakdown UI remains planned. No tracking pixel is installed on any website by this project.
- Workflow automation builder and SalesCompel Opportunity migration are planned. Existing periodic sync and scheduled posting are retained and default off.
- Composer drafts persist text, attachments and destinations. Platform privacy options and TikTok consent intentionally require review when reopening. Draft removal after successful publish can fail independently; review job status before posting again.
- HEIC upload storage is accepted by inherited handling, but conversion/compatibility for every provider is unverified. Providers may reject unsupported images/codecs. Multi-gigabyte uploads, streaming request-body limits and transcoding are not acceptance-tested.
- Browser bearer sessions retain FunnelHub's localStorage approach. HTTP-only session hardening, login rate limits, a first-setup concurrency guard, comprehensive CSP and a security review are required before public exposure.
- One Python worker is required: existing publish/sync locks are process-local. Multi-worker job claims/leases are not implemented.
- PostgreSQL locale is explicitly fixed to `en_US.utf8` for upstream migration comparison. Changing frozen upstream migration code/checksums is intentionally avoided.
- Portainer Git-stack instructions are provided but not exercised; no mserver stack was deployed from this workspace.

## Prioritized development after release blockers

1. Reliable large-file and physical iPhone publishing workflows, including upload cancellation/retry and provider-specific media validation.
2. Complete migration importer, conflict reconciliation and restore tests, with private token re-encryption.
3. Per-user identity/authorization, secure sessions and distributed scheduler leases if multiple users/workers are needed.
4. Broader CRM fields, Opportunities/pipeline adapters, pagination and deterministic company identity mapping.
5. Square product/inventory read views, GA4 traffic-source reporting, then explicitly authorized Gmail send/reply workflows.
6. Upstream update rehearsal: fetch SalesCompel, merge on a fresh integration branch, run its acceptance suite plus this fork's workflow, and keep each adapter change isolated.
