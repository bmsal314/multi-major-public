# Operations and rollback

## Intake and processing

`analysis_jobs` is the durable outbox. Jobs begin awaiting upload, become queued after exact object-size verification, and are claimed with a five-minute lease. Maximum three worker attempts; duplicate deliveries are harmless. A ten-minute authenticated maintenance sweep redispatches queued/expired processing work and retries terminal-job cleanup and account deletion.

Limits are deliberate pilot controls: one active job per account, five batches/hour, twenty/day, thirty alternative maps/hour, 300 ordinary API calls/minute/account. Auth limits allow 120 attempts/minute/IP plus ten/address/15 minutes so a shared campus network is not limited to a handful of total sign-ins. Provider limits also apply. Revisit these with actual abuse/capacity measurements rather than removing them.

## Alerts to configure before intake

| Signal | Initial action threshold |
| --- | --- |
| Oldest queued job | Investigate above 5 minutes |
| Terminal processing failures | Investigate sustained increase or >5% over 15 minutes |
| Cleanup failure event / orphan upload | Alert on any persistent failure; escalate approaching 24-hour retention target |
| Missing maintenance execution | Alert after 20 minutes |
| Saved-plan p95 | Investigate above 2 seconds |
| Three-audit p95 | Investigate above 60 seconds |
| Email delivery/bounces | Alert on delivery failure trend; close registration if confirmation cannot be delivered |
| Spending | Set owner-approved daily/monthly budgets and provider alerts before provisioning |

These are configuration instructions, not claims that dashboards or alerts are already running. The app emits only job UUID, attempt timing and aggregate cleanup/dispatch events. Configure queue and database metrics in provider dashboards without adding academic request-body logging. Record deletion failures and verify that repeated signed-URL uploads are eventually removed.

## Failure handling

- **Email outage:** set `AUTH_EMAIL_READY=false`, investigate SMTP/bounces; do not disable confirmation.
- **Queue outage:** stop new intake if retention targets are at risk. Jobs remain in PostgreSQL. Restore queue access, run authorized maintenance, verify duplicate delivery does not duplicate plans.
- **Worker crash:** verify expired lease reclaim and attempt limit, then inspect only content-free diagnostics. Do not download student PDFs into support tickets.
- **Cleanup outage:** retain job manifests/tombstones until all deletion attempts succeed. Do not delete metadata first. Suspend uploads if originals are approaching the disclosed retention deadline.
- **Credential compromise:** suspend intake, rotate service/internal/cron credentials, revoke sessions, audit access, notify the designated incident owner. Preserve appropriate logs without academic contents.
- **Concurrent saves:** 409 means the stored revision wins. The user may preserve their local changes manually or explicitly reload. Never force-write over another tab.

## Capacity exercise

After owner approval for staging usage/cost, prepare 100 verified synthetic accounts, each with a saved synthetic map. Put their email/password pairs in a mode-0600 file outside Git. Run:

```sh
backend/.venv/bin/python scripts/staging_load.py \
  --origin https://YOUR-STAGING-DOMAIN --accounts /PRIVATE/PATH/accounts.json \
  --allow-staging-load
```

The harness measures concurrent saved-map reads and twenty three-audit jobs, prints aggregate p95/error counts, and fails unmet targets. It has **not been run against cloud infrastructure**. Record actual Vercel/Supabase/email charges and queue/database bottlenecks from provider dashboards. Synthetic jobs remain in staging for inspection and should be deleted afterward. This is a capacity probe, not a university-scale certification.

## Backups and restoration

Select provider backup/PITR plans only with approval. Record actual RPO/RTO and retention. Export database schema/migrations, verify encrypted backup storage, and run a restore into an isolated staging project. Raw PDF retention should not be extended as a backup strategy. Maintain an independent backup of the original local SQLite/PDF files before personal migration.

Before each migration: take a verified backup, rehearse on staging, check RPC signatures and RLS, then deploy compatible application code. Prefer additive migrations and forward fixes. For this initial schema, restore to a new Supabase project if rollback is necessary; do not casually drop tables with student records.

For application rollback: pin the last verified Vercel deployment, pause queue intake/consumers if contracts changed, keep cleanup running, restore the compatible deployment, and verify jobs/saves across rollback. Do not roll the hosted service back to the unauthenticated local baseline.

## Institutional review

Before an institution-wide offer, prepare the data-flow diagram, subprocessor inventory, incident and backup evidence, penetration-test results, representative academic evaluation, accessibility results and a reviewed VPAT/ACR. Obtain contractual/privacy review and the institution's vendor approval. This repository does not assert certification or approval.
