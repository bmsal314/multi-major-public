# Verification and remaining release gates

## Executed locally — August 29, 2026 (second review pass)

- Original private regression suite: **115 passing**; ignored source PDFs and SQLite retained locally.
- Synthetic cloud suite: **42 passing**, exercising real generated PDFs, metadata, catalog deduplication, size/page limits, identity redaction, mixed-student rejection, defaults, credit preservation, edit replay, private API and extraction process. Three added this pass: the release allowlist keeps every deployment-critical file, a placeholder choice outside the requirement's listed courses is refused on replay, and two hand-added classes sharing a name in one term both survive.
- Combined backend suite: **157 passing** on the existing Python 3.11 virtual environment with the production dependency lock. Starlette emits a test-client deprecation warning; this is not a production failure. Python 3.12 execution remains a CI/staging gate.
- Disposable PostgreSQL: initial migration applied; anonymous and two-user isolation, direct write denial, storage paths, RPC restrictions, parent ownership, duplicate/stale worker completion, revisions, cascading deletion and upload tombstones asserted. The harness now pins the cluster locale, so it runs on macOS as well as CI rather than only in CI.
- Frontend TypeScript and production Next.js build passed. Security unit tests (**6 passing**) cover signed CSRF, exact Origin, cookie attributes, Unicode comparison, HTTPS configuration and fresh-token issuance.
- Deployed-boundary behaviour exercised against a locally running build: the session endpoint answers 200 with a CSRF token and `user: null` while signed out; a cross-origin POST, a missing or forged CSRF header, and a CSRF header without its cookie are each refused with 403; an unknown auth action is 404; the private API is 401 without a session; maintenance is 403 without the cron secret; and a production-mode HTTP origin fails closed.
- A simulated deployment bundle — the repository with every `.vercelignore` and `excludeFiles` exclusion removed from disk — imports `backend.main` and the queue subscriber cleanly, confirming the excluded legacy modules are genuinely unreachable from the hosted graph.
- npm audit and locked Python pip-audit reported **no known vulnerabilities**. This does not establish absence of vulnerabilities.
- Source scan found no personal names/emails in application source. The release script excludes private PDFs, SQLite, legacy auth/storage/API and private tests, then scans the new history, and now refuses to build a snapshot missing the Supabase migration, `frontend/next.config.js`, `vercel.json`, `.env.example` or the deployment guide. Final snapshot details are recorded by the release manifest.

## Defects found and fixed in the second pass

- The release allowlist accepted no `.sql` or `.js` file, so a published snapshot silently omitted `supabase/migrations/202608280001_platform.sql` — no schema to provision — and `frontend/next.config.js`, which sets every response security header. Both are now allowlisted, a named set of deployment-critical files is enforced, and a test asserts it.
- `session()` constructed a Supabase auth client before checking whether the visitor had any cookies, so an account-services outage returned an error from the endpoint that carries the CSRF token — disabling the sign-in form that would have recovered from it. Cookies are read first, and the session endpoint now degrades to "signed out" rather than erroring.
- The account page shared one `currentPassword` value between the change-password form and the delete-account form, so a password typed in the danger zone was sent with a password change. Each form now holds its own. A recovery link older than ten minutes also dead-ended on a hidden field; the field now returns with an explanation.
- The map editor accepted any course code for a reserved slot, showed it as filled, and saved — but the service's replay only honours a course the requirement lists, so the choice disappeared on the next load. The editor now applies the same rule, and any edit the service does refuse is reported in the workspace instead of surfacing only after a reload.
- Two hand-added classes with the same name in one term shared an identifier, so one replaced the other on reload. Identifiers are now unique.
- "Reset map" discarded every edit with no confirmation, and autosave wrote the result a second later. It asks first.
- Planning preferences were validated only by the service, whose refusal is a deliberately generic 422; a credit minimum above the ceiling or a cleared number field produced an unexplained failure. The fields are validated before submission, and the submit button says which of the four conditions is blocking it.
- The pre-med checklist read course placements from the plan the service last built rather than the map on screen, so it named the old term after any move.
- The results footer rendered mid-page with a panel below it, and the header, workspace, results and footer each used a different width and padding, so no two shared a left edge. All regions now sit on one rail and the workspace is a two-column layout.
- `docs/deployment-guide.html`, a self-contained offline runbook, is new in this pass.

## UI checks

The local headless-browser harness uses synthetic API fixtures for signed-in views; it does not validate live authentication. It does assert one real unfixtured behaviour: the session endpoint must return a usable CSRF token while signed out even when account services are unconfigured, because the sign-in form cannot submit anything without one. It checks desktop/mobile page overflow, keyboard movement/autosave and axe WCAG A/AA findings for welcome, workspace, map, account and privacy. Screenshots and axe reports are generated outside Git. The app's real unconfigured state is also checked to ensure registration fails closed. Final test output is the authority; an automated axe pass is not a WCAG conformance claim. Manual screen-reader and print/PDF accessibility review remain required.

## Must pass before real students

- Authenticate GitHub/Vercel, provision approved services, apply Supabase migration and verify environment separation.
- Build/deploy on Python 3.12; verify Vercel Services private binding, queue subscriber discovery, function limits, cron and billing.
- Send real signup/resend/recovery emails. Exercise expired/reused links, password change, global sign-out, session refresh/races, CAPTCHA and abuse behavior. Verify actual provider token revocation limits.
- Run two real Supabase accounts against every table/API/storage policy/RPC, including direct API access, exports, deletion and forged parent references. Local PostgreSQL tests use a minimal provider schema, not the production Auth/Storage service.
- Test interrupted upload, signed URL replay after processing/account deletion, oversized/encrypted/scanned PDFs, extraction timeout, duplicate delivery, process kill, cleanup failure and deletion during processing in staging.
- Run the 100-user/20-job capacity harness. Saved-map p95 <2s and typical three-audit p95 <60s are **targets, not measurements**. Record provider costs and limits.
- Validate consented representative audits with advisors, including transfer/repeat/minimum-grade/complex boolean requirements. Synthetic tests do not prove general DARS coverage.
- Complete manual keyboard, mobile, screen-reader and print review; document WCAG 2.2 AA findings and remediation.
- Configure monitoring, retention periods and support/incident contact; remove the privacy page's launch-gate placeholder only when those facts are known.
- Test backup restoration and deployment rollback. Obtain independent security, privacy/contract and accessibility reviews.

Release order: synthetic staging → original owner's verified account → small consented student pilot → separately approved institutional expansion. No real student rollout, university-wide readiness, cost target, backup restoration or vendor approval is claimed here.
