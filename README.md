
````markdown
<!-- README.md -->
# Ask-Flask

> A production-style LLM chat app with **React + Flask**, **SSE streaming**, **strict security headers**, **rate limiting**, **structured JSON logs**, and **server-backed Sessions** (create/rename/delete/export). Now with **session-pinned memory** **and a mini-RAG module** (FAISS + PII redaction + MMR + simple evals). <!-- CHANGED: mention RAG -->

<p align="center">
  <!-- Replace with real badge URLs when ready -->
  <em>Badges:</em>
  <img alt="CI" src="https://img.shields.io/badge/CI-GitHub_Actions-blue" />
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11.9-informational" />
  <img alt="Node" src="https://img.shields.io/badge/Node-20.x-informational" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-lightgrey" />
</p>

---

## Table of contents

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
* [RAG module](#rag-module) <!-- CHANGED: new section -->
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
    Routes[/app.py\n/health\n/api/chat\n/api/chat/stream\n/api/sessions*\n/api/rag/*/]  <!-- CHANGED: add /api/rag -->
    Obs[(observability.py\nJSON logs, request_id, errors)]
    Sec[(security.py\nCSP, HSTS, nosniff, frame-ancestors)]  <!-- CHANGED: custom module -->
    Limit[(ratelimit.py\nFlask-Limiter v3 shared budget)]
    Svc[services/openai_client.py\nretries + breaker]
    Store[services/session_store.py]
    Schemas[(schemas.py\nPydantic v2 DTOs)]
    PII[(security_utils/pii_redaction.py)]  <!-- CHANGED: PII lives outside security.py -->
    RAG[services/rag/*\nchunker, embeddings, FAISS, retriever, evals, agent] <!-- CHANGED -->
  end

  subgraph DB_And_Files [SQLite (dev) / Postgres (prod) + instance files]
    T1[(sessions)]
    T2[(messages)]
    F1[(server/instance/rag_index.faiss)]
    F2[(server/instance/rag_meta.json)]
  end

  UI <--> Routes
  Routes --> Sec
  Routes --> Limit
  Routes --> Obs
  Routes --> Schemas
  Routes --> Svc
  Routes --> Store
  Routes --> RAG
  RAG --> PII
  Store <---> DB_And_Files
  RAG <---> DB_And_Files
````

**Principles:** small, composable layers; typed DTOs; unified error bodies; **SSE** for realtime UX; **rate limits** and **security headers** on by default; observability everywhere.

---

## Key features

* **Streaming chat (SSE)** with graceful fallback to non-stream.
* **GFM Markdown** + PrismJS (**prism-tomorrow**) + Copy buttons with “Copied!”.
* **Sessions** (server-backed): list/create/delete/**rename**, **export** as JSON/Markdown.
* **Short-term context**: backend includes the most recent *N* exchanges (`CHAT_CONTEXT_MAX_TURNS`).
* **Pinned session memory**: compact summary stored on `Session.memory`; included in the system prompt and updated after each reply.
* **Mini-RAG**: ingest → chunk → **PII redact** → embed → **FAISS** index; **MMR** retrieve with citations; **tiny evals** (Recall@k, p95 latency) and a simple agent. <!-- CHANGED -->
* **Security by default**: CSP, HSTS, referrer-policy, frame-ancestors none, nosniff (via **custom `security.py`**). <!-- CHANGED -->
* **Reliability**: request IDs, structured logs, retries with jitter, minimal circuit breaker shim.
* **Cost & abuse controls**: 4000-char cap per message; **shared rate limit** across chat endpoints.

---

## Tech stack

**Frontend**

* React (Vite, ESM), `react-markdown` + `remark-gfm`, PrismJS.
* Plain CSS (no Tailwind). Vitest + jsdom tests.

**Backend**

* Python **3.11.9**, Flask, OpenAI Python SDK (wrapped by `OpenAIService`).
* **Flask-Limiter v3** (shared budgets), SQLAlchemy + Alembic, **Pydantic v2** DTOs.
* Structured JSON logs & request IDs, SSE streaming.
* **Custom `security.py`** for headers (Talisman **not used**). <!-- CHANGED -->

**Databases**

* Dev: SQLite (`server/instance/app.db`)
* Prod: Postgres (Render)

**RAG Add-on**

* `faiss-cpu`, `numpy`, OpenAI embeddings (default) with optional `sentence-transformers` fallback.

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

> **Tip:** Prefer absolute SQLite paths locally, e.g. `sqlite:///$PWD/server/instance/app.db`.

---

## Database & migrations

```bash
set -a; . ./.env; set +a
flask --app server.app:app db upgrade -d server/migrations
flask --app server.app:app db current -d server/migrations
echo "$DATABASE_URI"   # verify target DB
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

### RAG module <!-- CHANGED: new section -->

```
POST /api/rag/ingest
Body: { "docs":[{id, department, text}, ...], "overwrite": false }
200:  { ok, ingested, emb_model }

POST /api/rag/query
Body: { "query":"...", "k":4, "department":"Security", "mmr_lambda":0.6 }
200:  { ok, hits:[{score, doc_id, chunk_id, department, text}, ...] }

POST /api/rag/eval
Body: { "queries":[{"q":"...","expected_doc_id":"..."}], "k":4 }
200:  { ok, metrics:{ recall_at_k, p95_latency_ms, n } }

POST /api/rag/agent
Body: { "goal":"...", "k":4 }
200:  { ok, result:{ hits:[...], valid:true|false } }
```

---

## Security

* **Custom `security.py`** attaches headers at `after_request`:

  * **CSP** (`default-src 'self'`, blocks third-party script by default)
  * **HSTS**, **X-Content-Type-Options: nosniff**, **Referrer-Policy: no-referrer**
  * **X-Frame-Options: DENY**, basic **Permissions-Policy**
* Keep secrets out of Git; use `.env` locally and dashboard vars in Render.

---

## Observability

* Structured JSON logs with: `level, ts, request_id, path, latency_ms, model, error`.
* `X-Request-ID` echoed on all `/api/*`.
* Breadcrumbs for OpenAI calls and SSE start/complete.
* Pydantic v2 validation errors are **JSON-safe**.

---

## Rate limiting

* **Shared budget** across `/api/chat` and `/api/chat/stream` via Flask-Limiter v3.
* Success responses include:

  * `X-RateLimit-Limit`
  * `X-RateLimit-Remaining`
* 429 body uses the unified error shape.

---

## Session memory

**What it is:** a compact, durable summary stored on `Session.memory` (TEXT).

**How it’s used:**

* Included as a **pinned system message**:
  `Session memory (pinned): <summary>`
* Maintained after each successful reply (JSON & SSE) via a tiny LLM pass that merges old memory + the last turn, then trims to `CHAT_MEMORY_MAX_CHARS`.

**Config:**

* `CHAT_MEMORY_ENABLED=true`
* `CHAT_MEMORY_MAX_CHARS=2000`
* `CHAT_MEMORY_MODEL=gpt-3.5-turbo`

> Failures in memory update are logged but never break the request.

---

## RAG module

**Pipeline:** ingest → chunk (overlap) → **PII redact** → embed → **FAISS** index.
**Query:** top-k with optional **MMR** rerank & department filter.
**Citations:** each hit returns `{score, doc_id, chunk_id, department, text[:~220]}`.
**Evals:** simple harness (Recall@k, p95 latency).
**Agent:** minimal planner → tool executor → validator (default tool: `rag.search`).

**Quick demo:**

```bash
# Seed
curl -X POST http://localhost:5555/api/rag/ingest \
  -H "Content-Type: application/json" \
  --data @server/sample_kb.json

# Query with citations
curl -X POST http://localhost:5555/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What counts as PII and how should we handle it?","k":4,"mmr_lambda":0.6}'

# Tiny eval
curl -X POST http://localhost:5555/api/rag/eval \
  -H "Content-Type: application/json" \
  -d '{"queries":[
        {"q":"What counts as PII?","expected_doc_id":"Security-PII-Guide"},
        {"q":"How to run incident bridge?","expected_doc_id":"Oncall-Runbook"},
        {"q":"Do we use MMR and citations?","expected_doc_id":"RAG-Best-Practices"}
      ],"k":4}'

# Micro-agent
curl -X POST http://localhost:5555/api/rag/agent \
  -H "Content-Type: application/json" \
  -d '{"goal":"Show me RAG best practices","k":4}'
```

---

## Testing

**Backend (pytest)**

```bash
pytest -q server/tests/test_sessions_api.py
pytest -q server/tests/test_chat_api.py
pytest -q server/tests/test_chat_persistence.py  # includes no-persist-on-error (when added)
```

**Frontend (Vitest)**

```bash
npm test --prefix client
```

---

## CI/CD

* GitHub Actions: Python lint/type/tests + Node lint/build/tests.
* Optionally deploy `main` to Render.

---

## Render deployment

**Python version:** `runtime.txt` → `python-3.11.9`.

**Build**

```bash
pip install -r requirements.txt \
 && npm ci --prefix client \
 && npm run build --prefix client
```

**Start**

```bash
gunicorn server.app:app
# Alt: gunicorn --chdir server app:app
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
# CHAT_MEMORY_MODEL=gpt-3.5-turbo
```

**Health check:** `/health`

---

## Troubleshooting

* **Wrong DB migrated?**
  Check: `echo "$DATABASE_URI"`. Prefer absolute SQLite locally:
  `export DATABASE_URI="sqlite:///$PWD/server/instance/app.db"`

* **Module import issues in tests**
  Run pytest from repo root.

* **SSE behind proxies**
  Ensure: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.

---

## Roadmap snapshot

* ✅ Sessions CRUD + export + PATCH rename
* ✅ SSE streaming + fallback
* ✅ Markdown + Prism + Copy
* ✅ Rate limiting + security headers + JSON logs
* ✅ Context window & **pinned memory**
* ✅ **RAG** ingest/query/eval/agent
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



