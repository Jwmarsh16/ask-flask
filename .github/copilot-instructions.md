# Copilot Instructions for ask-flask

## Project Architecture
- **Backend (Flask):**
  - Located in `server/`.
  - Main entry: `server/app.py` (Flask app factory pattern).
  - Configurations: `server/config.py`.
  - Observability, rate limiting, and security handled in respective modules in `server/`.
  - Database: SQLite (`server/instance/app.db`), migrations via Alembic (`server/migrations/`).
  - Seeding: `server/seed.py`.
  - Tests: `server/tests/` (pytest conventions).

- **Frontend (React + Vite):**
  - Located in `client/`.
  - Main entry: `client/src/main.jsx`.
  - Components: `client/src/components/` (e.g., `ChatBot.jsx`).
  - Styles: co-located CSS files (e.g., `App.css`, `ChatBot.css`).
  - Vite config: `client/vite.config.js`.
  - ESLint config: `client/eslint.config.js`.

## Developer Workflows
- **Backend:**
  - Run dev server: `flask --app server/app run` (ensure `FLASK_APP=server/app.py` and proper env vars).
  - Migrations: `alembic` commands in `server/migrations/`.
  - Seed DB: `python server/seed.py`.
  - Tests: `pytest server/tests/`.

- **Frontend:**
  - Start dev server: `npm run dev` in `client/`.
  - Build: `npm run build` in `client/`.
  - Lint: `npm run lint` (ESLint rules in `client/eslint.config.js`).

## Patterns & Conventions
- **Backend:**
  - App factory pattern in Flask (`create_app()` in `server/app.py`).
  - Config via environment variables and `config.py`.
  - Observability, rate limiting, and security are modularized.
  - Alembic for DB migrations; migration scripts in `server/migrations/versions/`.

- **Frontend:**
  - React components use functional style and hooks.
  - CSS modules for component styles.
  - Vite for fast dev/build; config in `vite.config.js`.

## Integration Points
- **API:**
  - Frontend communicates with backend via REST endpoints (see `server/app.py`).
  - CORS and security handled in backend modules.

## External Dependencies
- **Backend:** Flask, Alembic, pytest, SQLite.
- **Frontend:** React, Vite, ESLint.

## Examples
- To add a new API route: update `server/app.py` and add tests in `server/tests/`.
- To add a new React component: create in `client/src/components/`, import in `main.jsx`.

---
For unclear or missing conventions, check `README.md` files or ask for clarification.
