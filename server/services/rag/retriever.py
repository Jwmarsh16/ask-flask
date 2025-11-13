# server/services/rag/retriever.py
# Path: server/services/rag/retriever.py
# Retrieve with optional metadata filter + MMR rerank. Returns citation-ready hits.

from typing import Dict, List, Optional
import numpy as np
from .embeddings import embed_texts
from .vector_store import FaissStore


def mmr_rerank(
    qv: np.ndarray,
    cand_vecs: np.ndarray,
    pool_idx: List[int],
    k: int,
    lam: float = 0.5,
) -> List[int]:
    """Maximal Marginal Relevance: balance relevance (to query) and diversity (among results)."""
    selected: List[int] = []
    chosen = set()

    for _ in range(min(k, len(pool_idx))):
        best_j, best_score = -1, -1e9
        for j in range(len(pool_idx)):
            if j in chosen:
                continue

            # Relevance: similarity between query and candidate
            rel = float(np.dot(qv[0], cand_vecs[j]))

            # Diversity: similarity to already selected candidates
            if not selected:
                div = 0.0
            else:
                sel_vecs = cand_vecs[selected]
                div = float(np.max(sel_vecs @ cand_vecs[j]))

            score = lam * rel - (1.0 - lam) * div
            if score > best_score:
                best_score, best_j = score, j

        chosen.add(best_j)
        selected.append(best_j)

    # Map local indices in the pool back to the global FAISS indices
    return [pool_idx[j] for j in selected]


def retrieve(
    query: str,
    store: FaissStore,
    k: int = 5,
    dept_filter: Optional[str] = None,
    mmr_lambda: Optional[float] = 0.6,
) -> List[Dict]:
    """
    Return top-k hits with trimmed text + citation metadata.

    Notes:
    - Safely handles empty/whitespace queries by returning [] instead of
      calling embed_texts and raising.
    - Applies optional department metadata filter.
    - Optionally applies MMR diversity re-ranking when mmr_lambda is not None.
    """
    # 🔹 Normalize and guard against empty queries (prevents embed_texts error)
    norm_q = (query or "").strip()  # <-- NEW: strip/normalize
    if not norm_q:
        return []  # no meaningful question → no hits

    # Embed the (normalized) query
    qv = embed_texts([norm_q]).astype(np.float32)

    # Search a slightly larger pool, then downselect via MMR
    D, I = store.search(qv, pool=25)
    pool = [(float(D[0][i]), int(I[0][i])) for i in range(len(I[0]))]

    # Optional metadata filter (e.g., department)
    if dept_filter:
        pool = [
            (s, idx)
            for (s, idx) in pool
            if store.meta[idx].get("department") == dept_filter
        ]
        if not pool:
            return []

    # Re-embed candidate texts to compute diversity for MMR
    if mmr_lambda is not None and pool:
        cand_texts = [store.meta[idx]["text"] for (_, idx) in pool]
        cand_vecs = embed_texts(cand_texts).astype(np.float32)
        pool_idx = list(range(len(pool)))
        selected_local = mmr_rerank(qv, cand_vecs, pool_idx, k, lam=mmr_lambda)
        selected = [pool[i] for i in selected_local][:k]
    else:
        selected = pool[:k]

    out: List[Dict] = []
    for score, idx in selected[:k]:
        md = store.meta[idx]
        text = md.get("text") or ""
        out.append(
            {
                "score": round(score, 4),
                "doc_id": md.get("doc_id"),
                "chunk_id": md.get("chunk_id"),
                "department": md.get("department"),
                "text": text[:220] + ("..." if len(text) > 220 else ""),  # trim for UI
            }
        )
    return out
