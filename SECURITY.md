# Security model

Email is among the most sensitive data an organization holds. This document
describes how `better-email` protects it, and — importantly — **which guarantees
are enforced by automated tests** (see `backend/tests/test_security.py`). A
privacy claim without a test rots the moment someone refactors.

## Leak surfaces and mitigations

### 1. The LLM provider (the biggest, most novel risk)
- **Provider abstraction is a privacy control.** The model is swappable via
  config (`LLM_PROVIDER`). Privacy-sensitive deployments can point at a local
  **Ollama** model (data never leaves the host) or a zero-retention endpoint —
  same code path.
- **PII redaction layer.** Before any text reaches a model, emails / phones /
  cards / SSNs are masked to placeholders (`<EMAIL_1>`) and restored on return.
  A single wrapper (`RedactingProvider`) is the choke point for every provider.
  *Tested:* no raw PII appears in what the provider receives; results come back
  un-redacted for the user.
- **Minimum context.** Providers receive neutral context objects (snippets,
  names), never full ORM rows.

### 2. Storage at rest
- **Secrets encrypted.** OAuth tokens / API keys are encrypted with a key
  derived from `SECRET_KEY` (`encrypt_secret`). *Tested:* plaintext never
  appears in the encrypted blob and round-trips correctly.
- **API keys hashed.** Stored only as salted hashes. *Tested.*
- `.env` is gitignored; only `.env.example` (blanks) is committed. *Tested* that
  no `.env` is present in the repo. CI also runs **gitleaks**.

### 3. Transport & access control
- **Auth-gated, owner-scoped API.** Every record carries `owner_id`; every query
  is scoped to the authenticated owner. *Tested:* unauthenticated and
  cross-tenant requests return 401/404, never data.
- **CORS is never `*`.** *Tested.* Production config refuses an insecure
  `SECRET_KEY` / `OWNER_API_KEY`. *Tested.*
- HTTPS is terminated by the platform (e.g. Railway) in production.

### 4. Self-inflicted leaks
- **No false merges.** Identity resolution is biased to *under*-merge; a wrong
  merge would expose one customer's data to another. Ambiguous matches become
  human-reviewed merge suggestions. *Tested:* two different people with similar
  names are never merged.
- **Log hygiene.** Message bodies and prompts are not logged at info level.
- **Reply is draft-only / human-sent** in v1, with an audit log.

## Reporting

For a real deployment, route security reports to a private channel and rotate
`SECRET_KEY` / `OWNER_API_KEY` if exposure is suspected. Secrets belong in the
host's secret manager (e.g. Railway variables), never in the repository.
