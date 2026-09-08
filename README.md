# Multi-Major

A private semester-planning tool for undergraduates managing more than one program. Upload text-based degree audit reports (DARS), confirm the interpreted programs, review an editable semester map, and return to saved plans. Independent software; no university affiliation or endorsement is implied.

**Status:** implemented and verified locally; not yet approved for broad student use. Live account storage, email, background job processing, capacity, backup restoration, and institutional review are the remaining release gates. See [verification](docs/VERIFICATION.md) and [deployment](docs/DEPLOYMENT.md).

## How it works

[`docs/PARSER_AND_PLANNING.md`](docs/PARSER_AND_PLANNING.md) documents the path from
an uploaded PDF to a term-by-term map: how General Studies designations are learned
from each document rather than looked up in a fixed table, how an elective is
recognised by its shape rather than its wording, and how term ceilings — including
the exam-prep semester's, which the student chooses — are enforced.

## Highlights

- Next.js frontend backed by a Python planning/parsing engine, deployed as a single web service.
- Verified-email accounts, password recovery/change, server-only session cookies, CSRF checks, CAPTCHA, distributed abuse limits and a nonce-based content-security policy.
- Row-level-security-scoped storage for parsed audits, jobs, preferences, plans and revisions; privileged background processing is kept separate from user-facing access.
- Private, object-specific uploads; durable queue processing; retryable original-file deletion.
- Pre-med tracking off by default, with a configurable per-term credit ceiling and no assumed minimum.
- Conservative, generic program metadata with catalog separation, stable requirement IDs, evidence locations, and explicit unknown-condition warnings. An unfamiliar audit produces a draft, not a verified graduation check.
- Editable maps with keyboard navigation, a print view, conflict detection, and account export/deletion.
- Requirements are categorized structurally, so a directed elective is scheduled instead of silently dropped; designations the tool hasn't seen before are read from the audit and reported rather than ignored.
- Per-term credit **and** class-count ceilings, both configurable.
- Saved maps are permutations: a dedicated view lists them with the metadata behind each decision, and any two can be compared side by side.
- The background worker credential holds no direct database privileges — only the specific functions it needs.

## Tests

```bash
backend/.venv/bin/python -m pytest        # 188 tests
cd frontend && npx tsc --noEmit
```

Test fixtures are synthetic and generated from source rather than committed — real degree audits carry a name, a student ID, and a full transcript, and are never checked in. `tests/conftest.py` rebuilds the fixtures when the suite runs.

## Local development

Use Node 24 and a Python 3.11+ virtual environment.

```sh
./setup.sh
cp .env.example .env
# Fill .env using a dedicated development database project; no production data.
make dev
```

Open `http://localhost:3000`. Registration stays unavailable until email delivery is configured. `make dev` starts the web and engine processes only; queue integration needs a local or staging queue environment.

```sh
make test          # synthetic tests, generated contracts, TypeScript, CSRF/cookies
make test-db       # disposable local PostgreSQL cluster; set POSTGRES_BIN when needed
make build
make audit
make test-ui       # requires a local production build and Playwright Chromium
```

Frontend types are generated from the backend's data models: `backend/.venv/bin/python -m scripts.generate_contracts`. Commit the generated output. Production dependency pins live in `backend/requirements.lock` and `frontend/package-lock.json`.

## Further reading

[Security boundaries](docs/SECURITY.md), [academic-coverage limitations](docs/ACADEMIC_COVERAGE.md), [operations and rollback](docs/OPERATIONS.md), and [migration instructions](docs/MIGRATION.md).
