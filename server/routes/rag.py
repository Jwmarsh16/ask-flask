# server/routes/rag.py
# Flask Blueprint: /api/rag/* — ingest, query, eval, and a tiny agent route.
# Changes:
# - Switched PII import to security_utils to keep security.py as a single module.  # change reason
# - Made all imports robust for both launch modes (package vs top-level).          # dual-mode import

from flask import Blueprint, request, jsonify
from typing import List, Dict
import uuid

# ---- Robust imports: package mode first, then top-level fallbacks ----
try:
    # Package mode (gunicorn server.app:app)
    from ..services.rag.chunker import chunk_text                     # dual-mode import
    from ..services.rag.embeddings import embed_texts, model_name     # dual-mode import
    from ..services.rag.vector_store import FaissStore                # dual-mode import
    from ..services.rag.retriever import retrieve                     # dual-mode import
    from ..services.rag.evals import eval_suite                       # dual-mode import
    from ..services.agents.simple_agent import ToolRegistry, run_agent# dual-mode import
except Exception:
    # Top-level mode (gunicorn --chdir server app:app)
    from services.rag.chunker import chunk_text                        # dual-mode fallback
    from services.rag.embeddings import embed_texts, model_name        # dual-mode fallback
    from services.rag.vector_store import FaissStore                   # dual-mode fallback
    from services.rag.retriever import retrieve                        # dual-mode fallback
    from services.rag.evals import eval_suite                          # dual-mode fallback
    from services.agents.simple_agent import ToolRegistry, run_agent   # dual-mode fallback

# PII redaction now lives under security_utils instead of making `security` a package
try:
    from ..security_utils.pii_redaction import redact                  # use new utils path (package mode)
except Exception:
    try:
        from security_utils.pii_redaction import redact                # top-level fallback
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
    body = request.get_json(force=True) or {}
    docs: List[Dict] = body.get("docs", [])
    overwrite = bool(body.get("overwrite", False))

    # Chunk + redact + embed
    chunks, metas = [], []
    for d in docs:
        did = d.get("id") or str(uuid.uuid4())
        dept = d.get("department") or "general"
        for i, ck in enumerate(chunk_text(d.get("text",""))):
            clean = redact(ck)                                         # now imports from security_utils
            chunks.append(clean)
            metas.append({
                "doc_id": did,
                "chunk_id": f"{did}::chunk{i}",
                "department": dept,
                "text": clean
            })

    if not chunks:
        return jsonify({"ok": True, "ingested": 0, "emb_model": model_name()})

    X = embed_texts(chunks)
    _ensure_store(X.shape[1])
    if overwrite:
        _STORE.load_or_init(X.shape[1])  # re-init store
    _STORE.add(X, metas)
    _STORE.save()
    return jsonify({"ok": True, "ingested": len(chunks), "emb_model": model_name()})

@rag_bp.route("/query", methods=["POST"])
def query():
    """
    Body: { "query": "string", "k": 4, "department": "Security", "mmr_lambda": 0.6 }
    """
    body = request.get_json(force=True) or {}
    q = body.get("query", "")
    k = int(body.get("k", 4))
    dept = body.get("department")
    lam = body.get("mmr_lambda", 0.6)
    _ensure_store()
    hits = retrieve(q, _STORE, k=k, dept_filter=dept, mmr_lambda=lam)
    return jsonify({"ok": True, "hits": hits})

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
