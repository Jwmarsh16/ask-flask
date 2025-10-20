
# Ask-Flask

> A production-style LLM chat app with **React + Flask**, **SSE streaming**, **strict security headers**, **rate limiting**, **structured JSON logs**, and **server-backed Sessions** (create/rename/delete/export). Now with **session-pinned memory** so chats “remember everything” in a compact summary. <!-- Added a succinct product pitch -->

<p align="center">
  <!-- Replace with real badge URLs when ready -->
  <em>Badges:</em>
  <img alt="CI" src="https://img.shields.io/badge/CI-GitHub_Actions-blue" />
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11.9-informational" />
  <img alt="Node" src="https://img.shields.io/badge/Node-20.x-informational" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-lightgrey" />
</p>

---

## Table of contents <!-- Added ToC for quick scanning -->

* [Architecture](#architecture)
* [Key features](#key-features)
* [Tech stack](#tech-stack)
* [Local quickstart](#local-quickstart)
* [Environment variables](#environment-variables)
* [Database & migrations](#database--migrations)
* [API reference](#api-reference)
* [Security](#security)
* [Observability](#observability)
* [Rate limiting](#rate-limiting)
* [Session memory](#session-memory)
* [Testing](#testing)
* [CI/CD](#cicd)
* [Render deployment](#render-deployment)
* [Troubleshooting](#troubleshooting)
* [Roadmap snapshot](#roadmap-snapshot)
* [License](#license)

---

## Architecture

```mermaid
flowchart LR
  subgraph Client [React (Vite)]
    UI[Chat UI\nreact-markdown + Prism\nCopy buttons]
    Sidebar[Session Sidebar\nlist/create/delete/rename/export]
    UI -- SSE / fetch --> API
  end

  subgraph Server [Flask API]
    Routes[/app.py\n/health\n/api/chat\n/api/chat/stream\n/api/sessions* /]
    Obs[(observability.py\nJSON logs, request_id, errors)]
    Sec[(security.py\nCSP, HSTS, nosniff)]
    Limit[(ratelimit.py\nFlask-Limiter)]
    Svc[services/openai_client.py\nretries + breaker]
    Store[services/session_store.py]
    Schemas[(schemas.py\nPydantic DTOs)]
  end

  subgraph DB [SQLite (dev) / Postgres (prod)]
    T1[(sessions)]
    T2[(messages)]
  end

  UI <--> Routes
  Routes --> Sec
  Routes --> Limit
  Routes --> Obs
  Routes --> Schemas
  Routes --> Svc
  Routes --> Store
  Store <---> DB
```

**Principles:** small, composable layers; typed DTOs; unified error bodies; **SSE** for realtime UX; **rate limits** and **security headers** on by default; observability everywhere. <!-- Added architecture principles -->

---

## Key features

* **Streaming chat (SSE)** with graceful fallback to non-stream.
* **GFM Markdown** + PrismJS (**prism-tomorrow**) + Copy buttons with “Copied!” feedback.
* **Sessions** (server-backed): list/create/delete/**rename**, **export** as JSON/Markdown.
* **Short-term context**: backend includes the most recent *N* exchanges (`CHAT_CONTEXT_MAX_TURNS`).
* **Pinned session memory**: compact summary stored on the `Session` row; included in the system prompt and updated after each reply. <!-- Highlights new memory feature -->
* **Security by default**: CSP, HSTS, referrer-policy, frame-ancestors none, nosniff.
* **Reliability**: request IDs, structured logs, retries with jitter, circuit-breaker shim.
* **Cost & abuse controls**: 4000-char cap per message; **rate limiting** with headers.

---

## Tech stack

**Frontend**

* React (Vite, ESM), `react-markdown` + `remark-gfm`, PrismJS.
* Plain CSS (no Tailwind). Vitest + jsdom tests.

**Backend**

* Python **3.11.9**, Flask, OpenAI Python SDK (wrapped by `OpenAIService`).
* Flask-Limiter v3, Flask-Talisman, SQLAlchemy + Alembic, Pydantic v2 DTOs.
* Structured JSON logs & request IDs, SSE streaming.

**Databases**

* Dev: SQLite (`server/instance/app.db`)
* Prod: Postgres (Render)

---

## Local quickstart

```bash
# 1) Python toolchain
pyenv install 3.11.9 -s
pyenv local 3.11.9
python -m venv .venv
source .venv/bin/activate

# 2) Install deps
pip install -r requirements.txt -r requirements-dev.txt
npm ci --prefix client

# 3) Set local env (creates SQLite in server/instance/app.db)
cat > .env <<'EOF'
DATABASE_URI="sqlite:///$PWD/server/instance/app.db"
OPENAI_API_KEY=dummy
FLASK_SECRET_KEY=dev
FRONTEND_ORIGIN=http://localhost:5173
CHAT_CONTEXT_MAX_TURNS=12
CHAT_MEMORY_ENABLED=true
CHAT_MEMORY_MAX_CHARS=2000
# CHAT_MEMORY_MODEL=gpt-3.5-turbo
EOF
set -a; . ./.env; set +a

# 4) Initialize/upgrade DB
flask --app server.app:app db upgrade -d server/migrations

# 5) Run backend (port 5555)
flask --app server.app:app run -p 5555 --debug

# 6) Run frontend (port 5173; proxies /api → 5555)
npm run dev --prefix client
```

Open [http://localhost:5173](http://localhost:5173)

---

## Environment variables

| Name                     | Purpose                           | Example                                                 |
| ------------------------ | --------------------------------- | ------------------------------------------------------- |
| `OPENAI_API_KEY`         | OpenAI access key (prod required) | `sk-...`                                                |
| `FLASK_SECRET_KEY`       | Flask session/signing key         | long random                                             |
| `DATABASE_URI`           | SQLAlchemy URL                    | `sqlite:///$PWD/server/instance/app.db` or Postgres URL |
| `FRONTEND_ORIGIN`        | Dev CORS allowlist                | `http://localhost:5173`                                 |
| `CHAT_CONTEXT_MAX_TURNS` | Prior exchanges to include        | `12`                                                    |
| `CHAT_MEMORY_ENABLED`    | Toggle pinned memory              | `true`                                                  |
| `CHAT_MEMORY_MAX_CHARS`  | Cap pinned memory length          | `2000`                                                  |
| `CHAT_MEMORY_MODEL`      | Model for memory summarization    | `gpt-3.5-turbo`                                         |

> **Tip:** Prefer absolute SQLite paths locally to avoid unexpected files, e.g. `sqlite:///$PWD/server/instance/app.db`. <!-- Added safety tip about SQLite paths -->

---

## Database & migrations

* Migrations live in `server/migrations/versions/`.
* Apply locally:

  ```bash
  set -a; . ./.env; set +a
  flask --app server.app:app db upgrade -d server/migrations
  flask --app server.app:app db current -d server/migrations
  ```
* If you accidentally pointed at Render Postgres, your migration ran *there*. Check:

  ```bash
  echo "$DATABASE_URI"
  ```

---

## API reference

### Health

```
GET /health → 200 { "status": "ok" }
```

### Chat (non-stream)

```
POST /api/chat
Body: { "message": string<=4000, "model": "gpt-3.5-turbo"|"gpt-4", "session_id"?: string }
200:  { "reply": "..." }
Errors: 400 validation, 413 too large, 429 rate limit, 503 circuit open, 5xx unified JSON
```

### Chat (SSE stream)

```
POST /api/chat/stream    Content-Type: application/json
Response: text/event-stream

Frames:
data: {"request_id":"..."}            # kickoff frame
data: {"token":"..."}                 # repeated
data: {"done":true}                   # terminal

Error (still 200 response):
data: {"error":"...", "code":503|500, "request_id":"...", "done":true}
```

### Sessions

```
GET    /api/sessions
POST   /api/sessions                  Body: { "title"?: string<=200 }
GET    /api/sessions/:id
PATCH  /api/sessions/:id              Body: { "title": string<=200 }  # non-empty, trimmed
DELETE /api/sessions/:id
GET    /api/sessions/:id/export?format=json|md  # attachment
```

> Server persists messages when `session_id` is supplied to chat routes.

---

## Security

* **Flask-Talisman** config sets: **CSP**, **HSTS**, **X-Content-Type-Options**, **Referrer-Policy**, and **frame-ancestors 'none'**.
* **No secrets in Git**. Use `.env` locally; set secrets in Render dashboard.
* Strict error handling: every `/api/*` error returns a unified JSON body with `request_id`.

---

## Observability

* Structured JSON logs with: `level, ts, request_id, path, latency_ms, model, error`.
* Request ID is echoed in `X-Request-ID` on all `/api/*`.
* Log breadcrumbs for OpenAI calls and SSE start/complete paths.
* Pydantic validation errors are **JSON-safe** (no 500s from bad error payloads).

---

## Rate limiting

* Shared budgets via **Flask-Limiter** across chat endpoints.
* On success, responses include:

  * `X-RateLimit-Limit`
  * `X-RateLimit-Remaining`
* 429 body uses the unified error shape.

---

## Session memory

**What it is:** a compact, durable summary stored on `Session.memory` (TEXT).
**How it’s used:**

* Included as a **pinned system message**:
  `Session memory (pinned): <summary>`
* Maintained after each successful reply (JSON & SSE) via a tiny internal LLM pass that merges old memory + the last turn, then trims to `CHAT_MEMORY_MAX_CHARS`.

**Config:**

* `CHAT_MEMORY_ENABLED=true` (toggle)
* `CHAT_MEMORY_MAX_CHARS=2000` (size cap)
* `CHAT_MEMORY_MODEL=gpt-3.5-turbo` (summarizer model)

> Failures in memory update are logged but never break the request. <!-- Clarifies failure mode -->

---

## Testing

**Backend (pytest)**

```bash
pytest -q server/tests/test_sessions_api.py
pytest -q server/tests/test_chat_api.py
pytest -q server/tests/test_chat_persistence.py
```

**Frontend (Vitest)**

```bash
npm test --prefix client
```

**Coverage targets**
CI enforces thresholds (see `vitest.config.js` and `pyproject.toml`).

---

## CI/CD

* GitHub Actions workflow runs: Python lint/type/tests + Node lint/build/tests.
* On push/PR: build client, run `pytest` and `vitest`, upload coverage.
* Optional: deploy on main to Render.

> Badge placeholders are included above—replace with your repo’s real badge URLs. <!-- Notes about placeholder badges -->

---

## Render deployment

**Python version:** pinned by `runtime.txt` → `python-3.11.9`.

**Build command**

```bash
pip install -r requirements.txt \
 && npm ci --prefix client \
 && npm run build --prefix client
```

**Start command**

```bash
gunicorn server.app:app
# (Alternative) gunicorn --chdir server app:app
```

**Env (Render)**

```
OPENAI_API_KEY=<secret>
FLASK_SECRET_KEY=<long random>
DATABASE_URI=postgresql://<USER>:<PASS>@<HOST>:5432/<DB>?sslmode=require
# Optional:
CHAT_CONTEXT_MAX_TURNS=12
CHAT_MEMORY_ENABLED=true
CHAT_MEMORY_MAX_CHARS=2000
```

**Health check:** `/health`

---

## Troubleshooting

* **Wrong DB got migrated**
  You likely pointed `DATABASE_URI` at Postgres. Check with:

  ```
  echo "$DATABASE_URI"
  ```

  Prefer absolute SQLite locally:

  ```
  export DATABASE_URI="sqlite:///$PWD/server/instance/app.db"
  ```

* **`ModuleNotFoundError: server` in tests**
  Run from repo root or add `conftest.py` at root that prepends the repo to `sys.path`.

* **Pylance can’t resolve imports**
  VS Code → **Select Interpreter** → `<repo>/.venv/...`.

* **SSE not streaming through a proxy**
  Ensure response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.

---

## Roadmap snapshot

* ✅ Sessions CRUD + export + PATCH rename
* ✅ SSE streaming + fallback
* ✅ Markdown + Prism + Copy
* ✅ Rate limiting + security headers + JSON logs
* ✅ Context window & **pinned memory**
* ⚠️ Tests: add explicit 429 path and “no-persist on error” checks
* ⏳ README GIFs (streaming, 429), analytics, theme toggle, token usage pill

---

## License

MIT (replace if different).

---

### Screenshots / GIFs (placeholders)

* `docs/streaming.gif` – SSE streaming in action
* `docs/rate-limit.gif` – rate-limit UX
* `docs/architecture.png` – diagram export

