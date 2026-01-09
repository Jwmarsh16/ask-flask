# server/routes/rag.py
# Flask Blueprint: /api/rag/* — ingest, query, eval, and a tiny agent route.
# Changes:
# - Switched PII import to security_utils to keep security.py as a single module.  # change reason
# - Made all imports robust for both launch modes (package vs top-level).          # dual-mode import

import uuid
from typing import Dict, List

from flask import Blueprint, jsonify, request

# ---- Robust imports: package mode first, then top-level fallbacks ----
try:
    # Package mode (gunicorn server.app:app)
    from ..services.agents.simple_agent import (  # dual-mode import
        ToolRegistry,
        run_agent,
    )
    from ..services.rag.chunker import chunk_text  # dual-mode import
    from ..services.rag.embeddings import embed_texts, model_name  # dual-mode import
    from ..services.rag.evals import eval_suite  # dual-mode import
    from ..services.rag.retriever import retrieve  # dual-mode import
    from ..services.rag.vector_store import FaissStore  # dual-mode import
except Exception:
    # Top-level mode (gunicorn --chdir server app:app)
    from services.agents.simple_agent import (  # dual-mode fallback
        ToolRegistry,
        run_agent,
    )
    from services.rag.chunker import chunk_text  # dual-mode fallback
    from services.rag.embeddings import embed_texts, model_name  # dual-mode fallback
    from services.rag.evals import eval_suite  # dual-mode fallback
    from services.rag.retriever import retrieve  # dual-mode fallback
    from services.rag.vector_store import FaissStore  # dual-mode fallback

# PII redaction now lives under security_utils instead of making `security` a package
try:
    from ..security_utils.pii_redaction import (
        redact,  # use new utils path (package mode)
    )
except Exception:
    try:
        from security_utils.pii_redaction import redact  # top-level fallback
    except Exception:
        # Safe no-op fallback if import ever fails in dev                # defensive fallback
        def redact(text: str, mask: str = "[REDACTED]") -> str:
            return text


rag_bp = Blueprint("rag", __name__)

# Singleton-ish store in-process
_STORE = FaissStore()


def _ensure_store(dim: int | None = None):
    if _STORE.index is None:
        if dim is None:
            dv = embed_texts(["init"])
            dim = dv.shape[1]
        _STORE.load_or_init(dim)


@rag_bp.route("/ingest", methods=["POST"])
def ingest():
    """
    Body: { "docs": [ { "id": "HR-1", "department": "HR", "text": "..." }, ... ], "overwrite": false }
    """
    from flask import (
        current_app,  # LOCAL import so module stays importable even without app context  # NEW
    )

    try:  # NEW: wrap whole ingest to avoid "Empty reply from server"
        body = request.get_json(force=True) or {}  # NEW: moved inside try
        docs: List[Dict] = body.get("docs", [])
        overwrite = bool(body.get("overwrite", False))

        # Chunk + redact + embed
        chunks, metas = [], []
        for d in docs:
            did = d.get("id") or str(uuid.uuid4())
            dept = d.get("department") or "general"
            for i, ck in enumerate(chunk_text(d.get("text", ""))):
                clean = redact(ck)  # now imports from security_utils
                chunks.append(clean)
                metas.append(
                    {
                        "doc_id": did,
                        "chunk_id": f"{did}::chunk{i}",
                        "department": dept,
                        "text": clean,
                    }
                )

        if not chunks:
            return jsonify({"ok": True, "ingested": 0, "emb_model": model_name()})

        X = embed_texts(chunks)  # may raise if OPENAI_API_KEY missing
        _ensure_store(X.shape[1])
        if overwrite:
            _STORE.load_or_init(X.shape[1])  # re-init store
        _STORE.add(X, metas)
        _STORE.save()
        return jsonify({"ok": True, "ingested": len(chunks), "emb_model": model_name()})
    except Exception as e:
        # Log rich error details, but don't crash the whole dev server      # NEW: logging instead of silent crash
        try:
            current_app.logger.error(
                "rag.ingest.error",
                exc_info=True,
                extra={"event": "rag.ingest.error"},
            )
        except Exception:
            # If logging itself fails, just continue to the JSON error      # NEW: defensive logging
            pass

        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(e),
                    "emb_model": model_name(),
                }
            ),
            500,
        )  # NEW: return JSON 500 instead of "Empty reply from server"


@rag_bp.route("/query", methods=["POST"])
def query():
    """
    Body (flexible keys):
      {
        "question": "string",          # preferred key
        "query": "string",             # legacy/alternate key (also accepted)
        "top_k": 4,                    # optional, alias for "k"
        "k": 4,                        # optional, fallback when top_k omitted
        "department": "Security",      # optional filter
        "mmr_lambda": 0.6              # optional diversity knob
      }
    """
    body = request.get_json(force=True) or {}

    # Accept both "question" and "query" to be client-friendly          # <-- NEW: accept question or query
    raw_q = body.get("question")
    if raw_q is None:
        raw_q = body.get("query")

    q = (raw_q or "").strip()  # <-- NEW: normalize/strip

    if not q:
        # Return a clean 400 instead of exploding in embed_texts        # <-- NEW: guard empty question
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Missing 'question' (or 'query') field",
                }
            ),
            400,
        )

    # Support both "top_k" and "k"                                      # <-- NEW: flexible k parsing
    raw_k = body.get("top_k", body.get("k", 4))
    try:
        k = int(raw_k)
    except (TypeError, ValueError):
        k = 4

    dept = body.get("department")
    if isinstance(dept, str):
        dept = dept.strip() or None  # <-- NEW: normalize dept to None when blank

    lam = body.get("mmr_lambda", 0.6)
    try:
        lam = float(lam)
    except (TypeError, ValueError):
        lam = 0.6

    _ensure_store()
    hits = retrieve(q, _STORE, k=k, dept_filter=dept, mmr_lambda=lam)
    return jsonify(
        {
            "ok": True,
            "query": q,  # <-- NEW: echo normalized query for debugging
            "hits": hits,
        }
    )


@rag_bp.route("/eval", methods=["POST"])
def eval_rag():
    """
    Body: { "queries": [ {"q":"...", "expected_doc_id":"HR-Leave-Policy"}, ... ], "k": 4 }
    """
    body = request.get_json(force=True) or {}
    queries = body.get("queries", [])
    k = int(body.get("k", 4))
    _ensure_store()
    metrics = eval_suite(queries, lambda q, kk: retrieve(q, _STORE, k=kk), k)
    return jsonify({"ok": True, "metrics": metrics})


@rag_bp.route("/agent", methods=["POST"])
def agent():
    """
    Body: { "goal": "user question here", "k": 4 }
    """
    body = request.get_json(force=True) or {}
    goal = body.get("goal", "")
    k = int(body.get("k", 4))
    _ensure_store()
    tools = ToolRegistry()
    tools.register("rag.search", lambda query, k=k: retrieve(query, _STORE, k=k))
    result = run_agent(goal, tools)
    return jsonify({"ok": True, "result": result})
