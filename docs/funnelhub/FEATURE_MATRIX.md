# Feature evidence and integration status

`Verified locally` means synthetic/local execution. `Mock-tested` means provider responses were simulated. Neither establishes that the user's account is authorized or that a live external API currently succeeds.

| Capability | SalesCompel source | FunnelHub source | Integration work / remaining gate |
|---|---|---|---|
| Account/Contact storage | Persistent Go/PostgreSQL API; 572 tests passed | Contact CRUD, CSV, relationships; 69-test suite passes | Preserve engine; add authenticated adapter and durable contact projection |
| CRM UI | Connected Vue editor; separate sample-data preview | React contact/pipeline UI builds | Reuse React shell; do not show preview data as live records |
| Login | OAuth/PKCE, refresh/JWT/client grants; separate DB roles | PBKDF2 + JWT owner login | Unified owner login gateway; per-user SSO federation planned |
| Pipeline | Not yet a complete workflow | Funnels/stages/deals, local CRUD | Reuse existing implementation; SalesCompel Opportunity model planned |
| YouTube | Not implemented | API-key stats, OAuth upload/analytics, publishing code | Reuse; mocked publishing tests; live grants/quota unverified |
| TikTok | Not implemented | OAuth/scopes, stats, direct/inbox publishing | Reuse; mocked tests; app review and actual grants unverified |
| Facebook | Not implemented | Page metrics/posts and publishing | Reuse; token/permissions/live API unverified |
| Instagram | Not implemented | Professional account metrics and publishing | Reuse; requires supported account and externally reachable media |
| Twitch | Not implemented | Client credentials/token channel and stream reads | Reuse; no general post/video publishing claimed |
| Media upload | Not implemented | Multipart upload and disk storage; hidden input UI | Repair native picker interaction; size limits, cleanup, persistent library |
| Drafts/planner | Not implemented | Post metadata drafts; composer lacks durable media drafts | Add durable composer drafts; preserve existing planner |
| Scheduling | Not implemented | In-process persisted jobs + status/retry | Reuse; single worker; publication gate defaults off in test stack |
| Gmail | Not implemented | IMAP/app-password ingestion and contact-linked viewer; mock-tested | Preserve; send/reply and Gmail OAuth not implemented |
| Square customers/orders | Not implemented | Customer/order/payment reads and local CRM upserts; mock-tested | Reuse, read-only remote calls; no live store operations during testing |
| Square products/inventory | Not implemented | Catalog counts only | Detailed product/inventory management not implemented |
| Website analytics | Not implemented | GA4 per-property/hostname reports and history; mock-tested | Reuse; no invented visitors; traffic-source breakdown requires expansion |
| Automation builder | Planned | Periodic sync and scheduled publication only | Label workflow builder as planned; retain real scheduler status |
| Secrets | Hashed/segregated CRM identities | Fernet integration secrets; browser bearer token | Server-only CRM principal; preserve key securely; browser session hardening pending |
| Docker | No turnkey production stack in inspected root | Single container + persistent SQLite/media volume | Isolated PostgreSQL + app + one-shot initializer; Docker execution pending |
| Production migration | Planned | Additive startup migrations | Assessment/dry-run only; no production import or credential copy |

The source baseline initially failed seven tests because this execution environment sets a SOCKS proxy but the optional HTTPX socks dependency was missing. Installing socksio resolved all seven; they are not presented as product bug fixes. See TESTING.md for final executed checks and known gaps.

## Completed integration evidence

The added adapter, account UI, transactional contact projection, media library, native file-input control, durable composer drafts, private media route, test publication gates, Compose files, read-only migration assessor and documentation are implemented. Actual PostgreSQL API/restart acceptance passes; integrated provider/regression tests pass (83), and unchanged SalesCompel Go tests pass (572). Browser execution and Docker deployment remain separate pending gates. See TESTING.md and KNOWN_ISSUES.md for exact boundaries.

## Acceptance classification

| Feature group | Working in SalesCompel | Working in FunnelHub | Requires integration | Requires repair | Not yet implemented |
|---|---|---|---|---|---|
| CRM accounts and contacts | Verified persistent API | Contact CRUD verified | Adapter/projection implemented and verified locally | Production reconciliation and scale limits | Bidirectional contact edits |
| Unified login | Verified in upstream suite | Owner login verified | Server gateway implemented | Session hardening before exposure | Per-user OAuth federation |
| Social providers | No | Mock-tested implementations; live state unknown | Existing implementations reused | Validate current grants/API behavior with sandbox accounts | Twitch publishing unsupported |
| Publishing and scheduling | No | Mock-tested job execution | Existing jobs retained; test action gate added | Live delivery and restart/idempotency rehearsal | Distributed job queue |
| Native media upload | No | Backend verified; original picker interaction defective | Persistent private library implemented | Desktop/mobile browser acceptance pending | Physical iPhone verification |
| Composer drafts | No | Original metadata drafts only | Durable text/media/channel drafts implemented and API-tested | Browser reload acceptance pending | Scheduled-time/options persistence in composer draft |
| Gmail | No | Mock-tested IMAP reads and contact links | Existing reader retained | Live authorized account validation | Gmail OAuth and send/reply |
| Square | No | Mock-tested customer/order/payment reads | Existing adapter retained; contacts project to CRM | Sandbox read-only validation | Product/inventory editor |
| Website analytics | No | Mock-tested GA4 per-site/history | Existing reports exposed in unified navigation | Real-property validation | First-party tracker; dedicated referral UI |
| Deployment/migration | No turnkey stack | Existing SQLite deployment | Separate Compose stack and dry-run assessor added | Docker/browser/server acceptance; restore rehearsal | Production importer |

No provider is classified as production-ready solely because its mocked tests pass. Production readiness requires the live/sandbox and deployment gates listed above.
