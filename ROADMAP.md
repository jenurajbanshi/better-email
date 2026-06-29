# Roadmap

This file tracks the feature set, what's shipped, what's next, and the known
risks for `better-email`. It captures the scoping decisions made before
implementation so they aren't lost in chat history.

Legend: ✅ done · 🔜 planned (high value) · 🧊 deliberately deferred

---

## ✅ Shipped (v1 vertical slice)

The whole product runs offline, end-to-end, with no API key and no Gmail.

- **Customer-grouped inbox** — one row per customer, not per message;
  accountability-first sorting (forgotten → needs-response → priority →
  recency).
- **Cross-channel identity stitching** — thread reply, brand-new email, a
  *different* address, and a web form collapse into one customer.
  Deterministic-first (normalized email incl. gmail dots/`+tags`, phone,
  thread), LLM for the ambiguous remainder.
- **Bias to under-merge** — ambiguous matches become human-reviewed **merge
  suggestions** (accept/reject), never silent merges.
- **Request/case grouping** — same thread ⇒ same request; otherwise the LLM
  decides new vs. follow-up. A customer can hold several distinct requests.
- **Triage** — AI summary, extracted "the ask", priority, sentiment.
- **Direction-aware status** — `needs_reply` / `waiting` / `resolved`, with
  resolve / reopen.
- **"Never forgotten" detection** — requests awaiting our reply past an SLA
  threshold (`FORGOTTEN_AFTER_HOURS`) are flagged and surfaced first.
- **Draft replies (human-sent)** — AI draft + send (flips status to waiting);
  audit-logged. Send is draft-only by design in v1.
- **Pluggable LLM provider** — `mock` (default), `openai`, `anthropic`,
  `ollama`, selected by env, behind a PII-redaction wrapper.
- **Pluggable connectors** — `mock` (rich seed) default; `gmail` OAuth scaffold
  with least-privilege scopes.
- **Security** — owner-scoped, auth-gated API; encrypted secrets at rest; hashed
  API keys; CORS never `*`; prod config validation; PII redaction before any LLM
  call. Each guarantee has a test (see `SECURITY.md`).
- **Persistence** — SQLite (local/demo) ↔ Postgres (`DATABASE_URL`), no code
  change.
- **Deploy/ops** — single-image `Dockerfile` (API serves the SPA),
  `docker-compose.yml` (SQLite default, `--profile pg` for Postgres),
  `Makefile`, Railway notes.
- **Tests & CI** — 27 offline tests (functional + golden-scenario + security);
  CI runs tests, frontend build, dependency audit, and gitleaks.

---

## 🔜 High-value follow-ups

- **Live Gmail connector** — finish the OAuth flow (token storage encrypted via
  the existing `encrypt_secret`), incremental sync, and Pub/Sub push vs. polling.
  *Touches:* `connectors/gmail.py`, a credentials table, `services/sync.py`.
- **Real-model eval harness** — turn the golden scenarios into an accuracy/regression
  suite so swapping models (or prompts) is measurable. *Touches:* `tests/`, a new
  labeled fixture set, a small scoring script.
- **Background-sync worker** — promote in-process sync to a dedicated worker /
  Railway cron calling the sync service. *Touches:* `services/sync.py` (already a
  standalone callable), deploy config.
- **Multi-user accounts** — real login (email/password or OAuth) and per-user
  scoping. The `owner_id` column is already everywhere, so this is additive.
- **Quote-stripping & auto-reply detection** — strip quoted history and skip
  out-of-office/bounces before triage (cheaper, more accurate). *Touches:*
  ingest/normalization.
- **Manual split / re-assign** — split a wrongly grouped request, move a message
  to another customer; feed corrections back as ground truth.
- **Attachments** — store/reference attachments; search.
- **Team assignment** — assign requests to teammates; round-robin; per-assignee
  "forgotten" views.
- **Richer search & filters** — by status/priority/channel/customer; full-text
  (and vector search for fuzzy identity at scale, a reason to graduate to
  Postgres).
- **Per-customer notes UI** — the API exists (`PUT /customers/{id}/notes`); add
  the frontend affordance.
- **GDPR/CCPA delete** — per-customer purge of messages + derived AI artifacts
  (cascade deletes + owner scoping already in place).

---

## 🧊 Deliberately deferred

- Calendar / scheduling integration.
- Analytics dashboards & reporting.
- Mobile app.
- Full bidirectional label/folder sync with the source platform.
- Auto-send / fully autonomous replies (kept human-in-the-loop on purpose).

---

## Known risks / "unknown unknowns"

These shape the data model and engine and are worth keeping visible.

1. **False merges are worse than false splits** — a wrong merge exposes one
   customer's mail to another. Mitigation: under-merge bias + reversible,
   audited merges. (Tested.)
2. **Direction detection** — "awaiting our reply" depends on reliable
   inbound/outbound classification, which is messy for forms/aliases. Needs
   per-connector logic.
3. **Email parsing swamp** — quoted chains, HTML vs. plaintext, signatures,
   auto-replies, lists, bounces. Feeding quoted history to the LLM hurts
   grouping and burns tokens.
4. **LLM cost/latency at inbox scale** — deterministic-first funnel + cached
   identity decisions keep it bounded; revisit with batching/caching.
5. **Model drift** — swapping models can silently change grouping; the eval
   harness is the guard.
6. **Two-way action safety** — sending (especially AI-drafted) needs the
   human-in-the-loop gate, idempotency, and audit trail already started here.
7. **Right-to-be-forgotten** — clean deletion path for stored PII + AI
   summaries.
