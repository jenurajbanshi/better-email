# better-email

An improved, **customer-centric** email client. Instead of a message/thread
list, the inbox becomes a list of **customers** and their **open requests** —
stitched together across channels so that **no customer is ever left
forgotten**.

It is **extensible to other platforms** (Gmail first) and **model-agnostic**
(swap the LLM via one env var). It runs **fully offline out of the box** with a
mock connector + mock LLM provider, and is **Railway-ready** (single container,
SQLite locally → Postgres via `DATABASE_URL`).

---

## The idea

Conventional clients are *message-centric*. This one is *customer-centric*. The
hard problem is **identity resolution + request grouping**: the same person may
reach you by replying in a thread, starting a brand-new email, writing from a
*different address*, or filling a *web form*. A naive client shows four
unrelated items; this one collapses them into **one customer with N requests**
and tracks which requests are awaiting your reply.

Three engines power it:

1. **Identity engine** — entity resolution across addresses / forms / names.
   Deterministic-first (exact + normalized email, gmail dots/`+tags`, phone,
   thread), LLM only for the ambiguous remainder. **Biased to under-merge**: a
   false merge leaks one customer's data into another, so ambiguous cases become
   human-reviewed **merge suggestions**, never silent merges.
2. **Grouping engine** — same thread ⇒ same request; otherwise the LLM decides
   new vs. follow-up.
3. **Triage / accountability engine** — summary, the ask, priority, sentiment,
   direction-aware status (`needs_reply` / `waiting` / `resolved`), and
   **forgotten detection** (awaiting our reply past an SLA threshold). The inbox
   is sorted accountability-first.

## Architecture

```
Connector (gmail | mock | …)  ─►  normalized Message
        │
        ▼
  Ingest pipeline ─► Identity engine ─► Grouping engine ─► Triage engine
        │                                                      │
        ▼                                                      ▼
   SQLite / Postgres  ◄──────────────  owner-scoped REST API  ──►  React SPA
                                            │
                                   LLM provider (mock | openai | anthropic | ollama)
                                   behind a PII-redaction wrapper
```

- **Backend:** Python + FastAPI + SQLAlchemy (SQLite ↔ Postgres, no code change).
- **Frontend:** React + Vite + TypeScript + Tailwind.
- **Everything downstream of a connector speaks one normalized schema**, so new
  platforms and new models plug in without touching business logic.

## Quick start (offline, no keys)

```bash
# Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000     # API at http://localhost:8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                                    # UI at http://localhost:5173
```

In the UI: enter the API key (`dev-owner-key-change-me` by default), click
**Connect**, then **Sync now**. You'll see the seeded customers — including
"Sarah Chen", who arrives via two email addresses *and* a web form, grouped into
one customer with her requests, the stale one flagged ⚠ **forgotten**.

Or run the whole thing as one container:

```bash
docker compose up --build          # http://localhost:8000
```

## Configuration

Copy `.env.example` to `.env` (or set these as host variables). Highlights:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `sqlite:///...` (default) or `postgresql+psycopg://...` |
| `LLM_PROVIDER` | `mock` (default), `openai`, `anthropic`, `ollama` |
| `LLM_MODEL` | model name for the chosen provider |
| `LLM_REDACT_PII` | redact PII before any LLM call (default `true`) |
| `CONNECTOR` | `mock` (default) or `gmail` |
| `OWNER_API_KEY` | API key for the single-owner gate |
| `SECRET_KEY` | encrypts secrets at rest; required strong in prod |
| `CORS_ORIGINS` | allowed frontend origins (never `*`) |
| `FORGOTTEN_AFTER_HOURS` | SLA threshold for "forgotten" (default 24) |

## Extending

- **New platform:** implement `Connector` (`backend/app/connectors/base.py`).
  See `mock.py` (offline seed) and `gmail.py` (OAuth scaffold, least-privilege
  scopes). Register it in `services/sync.py`.
- **New model:** implement `LLMProvider`, or subclass `JSONChatProvider` and
  just provide `_complete()`. Wire it into `llm/factory.py`. It is automatically
  wrapped by the PII-redaction layer.

## Deploying to Railway

1. Connect the repo — Railway builds the `Dockerfile` (API + built SPA in one
   image).
2. Add the **Postgres** plugin; Railway injects `DATABASE_URL` (picked up with
   no code change).
3. Set variables: `SECRET_KEY`, `OWNER_API_KEY`, `APP_ENV=prod`, `CORS_ORIGINS`,
   and your `LLM_PROVIDER`/keys.
4. The app serves the SPA and API on `$PORT`. Periodic sync can later move to a
   Railway cron job calling the sync service.

## Testing & security

```bash
cd backend && . .venv/bin/activate && python -m pytest      # 27 tests, offline
```

Security is part of the test suite (PII never reaches the model, tenant
isolation, secret encryption, no false merges, prod config validation). See
[`SECURITY.md`](./SECURITY.md). CI (`.github/workflows/ci.yml`) runs backend
tests, the frontend build, a dependency audit, and a secret scan.

## Status / roadmap

Shipped: the full offline vertical slice (engine + API + UI + mock environment +
tests + Docker/CI). Natural follow-ups: live Gmail OAuth hookup, real-model
evaluation against the golden scenarios, background-sync worker, and multi-user
accounts (the `owner_id` scoping is already in place).
