# Deployment: synthetic staging first

For a step-by-step walkthrough with commands, expected output and per-step checkpoints, open
[`deployment-guide.html`](deployment-guide.html) from disk. It is offline and self-contained; this
page is the same material in prose and remains the reference for the reasoning behind each choice.

No resources have been provisioned. Do not enable registrations or accept real student records until the staging gates in VERIFICATION.md pass. Paid provisioning requires the owner's approval.

## Provider setup

1. Authenticate GitHub and Vercel. Publish the **clean snapshot** to a new private repository; do not push the baseline or its history. Enable secret scanning and branch protections. CI needs read-only repository access.
2. Create separate Supabase projects and Vercel environments for development, staging and production. Choose approved, compatible data regions; use `iad1` for queues unless the deployment design is changed. Never give preview deployments production credentials.
3. Apply `supabase/migrations/202608280001_platform.sql` to a new dedicated Supabase project, using the migration administrator. The release snapshot carries this file; a snapshot without it cannot provision a database, and `make release` now refuses to build one that omits it, `frontend/next.config.js`, `vercel.json`, `.env.example` or the deployment guide. It is an initial migration, not a script to rerun on an existing schema. Verify RLS and storage policies with two real test accounts. Do not expose the `private` schema through PostgREST.
4. Keep Supabase email confirmation enabled. Set a 12-character minimum, appropriate session/JWT expiry, refresh-token reuse protection, and provider abuse controls. Disable anonymous sign-in. Use short-lived access tokens; revoking refresh sessions does not immediately invalidate already-issued JWTs.
5. Configure a verified sending domain in Resend and custom SMTP in Supabase. Set From address, SMTP credentials, DKIM/SPF/DMARC and bounce handling. Disable email click tracking. Do not put Resend credentials in the browser or app source. Confirm actual signup/recovery delivery before setting `AUTH_EMAIL_READY=true`.
6. Configure Turnstile for the exact app domains. The application verifies Turnstile tokens at its server boundary. If enabling Supabase's additional native CAPTCHA, adapt and test the token flow: one-use tokens must not be verified twice. Default provider email service is not a production substitute.
7. In Vercel choose **Services** as the project framework, repository root as project root, and the clean branch as production branch. Services and Python Queues are beta features; confirm availability and subscriber discovery in the actual account before deploying. `web` alone has a public rewrite. The internal binding supplies `ENGINE_URL`; do not set a production localhost URL.
8. Verify Python **3.12**, Node **24**, worker limits, function regions, subscriber `backend.cloud.worker:consume_analysis`, topic `audit-analysis`, consumer group `parser-v2`, and ten concurrent consumers. Inspect the generated deployment bundle for PDFs, SQLite, secrets, tests and legacy services before promotion. Verify the worker function's duration supports the 90-second total extraction budget.
9. Configure maintenance cron every ten minutes with `CRON_SECRET`. Frequent cron and commercial use may require a paid Vercel plan: obtain approval first. Verify cron authentication, queue access/OIDC, billing limits, alert delivery and cleanup before student uploads.

## Environment

Use `.env.example` as the inventory. All keys except `NEXT_PUBLIC_TURNSTILE_SITE_KEY` stay server-side. `SUPABASE_SECRET_KEY` is an administrative credential and bypasses RLS. `SUPABASE_PUBLISHABLE_KEY` is used with each student's bearer token for normal database requests. Use Supabase's current publishable/secret keys; this implementation does not assume a legacy service-role JWT in place of the secret key. The privileged client sends the secret key in both `apikey` and `Authorization`, which the Auth admin endpoints require and which Supabase permits while the two values are identical, so a legacy service-role JWT also works without code changes.

Generate independent random values of at least 32 bytes for `INTERNAL_API_SECRET` and `CRON_SECRET`. `APP_ORIGIN` must be the exact HTTPS origin. Each preview environment needs an explicit origin; wildcards and arbitrary callback redirects are not accepted. Never paste credentials in tickets, chat, Git, or logs.

## Email templates

Supabase **Confirm signup** link, substituting the actual fixed deployment origin:

```html
<a href="https://YOUR-APP-DOMAIN/confirm?token_hash={{ .TokenHash }}&type=signup">Confirm your account</a>
```

Recovery:

```html
<a href="https://YOUR-APP-DOMAIN/confirm?token_hash={{ .TokenHash }}&type=recovery">Reset your password</a>
```

Allowlist only the exact `/confirm` URL in Supabase. The page requires a button click before redemption to reduce accidental consumption by link scanners. Expired/reused tokens fail safely. Exclude query strings on `/confirm` from logs and monitoring; token hashes are sensitive. Do not use templates that place access/refresh tokens in URL fragments.

## References checked August 28, 2026

[Vercel Services configuration](https://vercel.com/kb/guide/vercel-services), [Python runtime](https://vercel.com/docs/functions/runtimes/python), [Queues](https://vercel.com/docs/queues), [function limits](https://vercel.com/docs/functions/limitations), [Supabase SMTP](https://supabase.com/docs/guides/auth/auth-smtp), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security). The installed `vercel-queue` 0.8.0 package documents Python subscriber discovery. Staging verification takes precedence over cached documentation.
