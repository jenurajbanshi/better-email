.PHONY: help install backend frontend dev test build docker

help:
	@echo "make install   - install backend + frontend deps"
	@echo "make backend   - run the API (http://localhost:8000)"
	@echo "make frontend  - run the Vite dev server (http://localhost:5173)"
	@echo "make test      - run backend tests (offline)"
	@echo "make build     - build the frontend bundle"
	@echo "make docker    - build and run the single-container app"

install:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && . .venv/bin/activate && python -m pytest

build:
	cd frontend && npm run build

docker:
	docker compose up --build
