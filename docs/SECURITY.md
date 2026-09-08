# Security and data boundaries

This is a pilot implementation, not a security certification or a claim of FERPA compliance.

## Trust model

The browser receives no access/refresh tokens or administrative keys in JSON or localStorage. Authentication uses server-managed Secure, HttpOnly, SameSite=Lax cookies in production. Mutations require an exact Origin and signed CSRF cookie/header pair. Login, registration, recovery and destructive verification use database-backed abuse limits. Web HTML is dynamically rendered with a fresh CSP script nonce; private API responses are no-store.

Normal requests verify the current Supabase user and confirmed email, then call PostgreSQL with that user's JWT and the publishable key. Per-request clients are never shared. Authenticated users have SELECT-only owner policies on application tables; bounded SECURITY DEFINER RPCs derive ownership from `auth.uid()`, validate parent ownership, and perform atomic changes. Direct row writes are denied. There are no public views. User-owned plan results remain student-editable planning records, not authoritative university records.

Administrative Supabase keys bypass RLS. Queue workers, account deletion and maintenance need that privilege; auth abuse counters also use a narrowly exposed service-only RPC. These are explicitly trusted server operations, not evidence that RLS protects against a compromised server. Vercel environment credentials may be shared across functions in one project: a compromised server could expose administrative access. Isolating worker credentials into separately controlled infrastructure and using narrowly scoped database roles is a further institutional security review item. Do not claim per-function credential isolation that the deployment has not established.

## Uploads and retention

A verified user creates an owner-bound job manifest before receiving object-specific upload URLs. Storage is private: no student SELECT/read/list or overwrite policy. Direct upload bypasses the function payload ceiling. Limits: eight PDFs, 25 MB/80 pages per PDF, 100 MB per batch. The worker checks actual object size and manifest ownership. Extraction runs in a credential-free child process with CPU, memory (Linux), output and wall-clock limits. It rejects non-PDF, encrypted, textless and overly complex input. Native PDF code still requires patching and a hostile-file security review.

Originals are deleted after success or terminal failure. Cleanup sweeps abandoned uploads and retries failed deletions. Signed upload URLs remain valid for two hours even after deleting a file: cleanup keeps opaque paths and repeats deletion through the expiry margin. Account deletion leaves only temporary private tombstones, with no academic content, for the same reason. Monitor cron, cleanup backlog and storage age; outages can delay deletion. Provider backups and logs have separate retention, which must be configured and disclosed before launch.

Parsed course records may include grades and GPA because planning evidence needs them. Identifying header lines, email addresses and student-ID patterns are removed; filenames are not sent to the initialization API. Redaction is heuristic and must be validated on consented representative reports. Unknown layouts can contain identifying information in unexpected places. Do not describe it as guaranteed anonymization. No AI model receives audits.

## Concurrency and failure behavior

Jobs are recorded before dispatch. Queue deliveries contain only a job UUID. Database leases, attempts and transactional completion prevent duplicate audits/plans. Old jobs create separate results, never overwrite an existing map. A maintenance outbox sweep recovers missed dispatch. Plan saves compare revisions in a transaction; stale writes return 409. The UI preserves unsaved changes, stops automatic retries after an error, and offers explicit reload.

Account deletion first disables new work and cancels jobs. Worker completion rechecks account state. Storage cleanup precedes Auth deletion, with maintenance retries. Reauthentication is required at the web boundary. Local passwords/sessions are never imported.

## Operational requirements

No request-body logging, academic exception output, signed URLs, token query strings or full student filenames. Content-free job UUID, duration, status, queue age and failure counts are sufficient. Review Vercel/Supabase platform logs separately; application logging controls do not configure provider logs.

Run dependency audits and secret scanning in CI; retain an independent penetration test and deployed two-user RLS/storage/RPC exercise as release gates. Rotate compromised credentials, invalidate sessions, stop intake, preserve content-free incident evidence, and follow the incident runbook. The source scanner is a guardrail, not comprehensive DLP.
