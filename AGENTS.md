# better-email

See `README.md` for the product overview and standard commands, and the `Makefile`
for the canonical install/run/test/build targets.

## Cursor Cloud specific instructions

This is a two-service app that runs **fully offline by default** (mock email
connector + mock LLM), so no API keys or external services are needed to develop
or test it.

### Services

| Service | Dir | Dev command | URL |
|---|---|---|---|
| Backend (FastAPI) | `backend/` | `make backend` (uvicorn `--reload`, port 8000) | http://localhost:8000 |
| Frontend (React + Vite) | `frontend/` | `make frontend` (Vite dev server) | http://localhost:5173 |

Lint/test/build (see `Makefile` / `README.md`):
- Backend tests: `make test` (pytest, runs fully offline).
- Frontend type-check: `cd frontend && npm run lint` (`tsc --noEmit`).
- Frontend build: `make build` (`tsc --noEmit && vite build`).

### Non-obvious notes

- The backend venv lives at `backend/.venv`. The dependency-refresh/update script
  creates it and installs `backend/requirements.txt`; activate it with
  `. backend/.venv/bin/activate` before running uvicorn/pytest manually.
- Creating the venv requires the system package `python3.12-venv` (already present
  in the VM snapshot). Stock `python3 -m venv` fails without it.
- The default owner API key is `dev-owner-key-change-me` (from `OWNER_API_KEY`).
  In the UI you must paste this key, click **Connect**, then **Sync now** before
  any customers appear — the SPA does not auto-sync on load.
- The owner row is bootstrapped on first request using `OWNER_API_KEY`; changing
  the key after first run won't re-bootstrap.
- Data persists in a SQLite file at `backend/better_email.db` (created on first
  run). Delete it to reset the seeded demo data.
- API auth is via the `X-API-Key` header (or `Authorization: Bearer <key>`); every
  query is scoped to the owner.
