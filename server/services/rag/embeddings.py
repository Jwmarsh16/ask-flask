# server/services/rag/embeddings.py
# Embeddings backend for RAG:
# - Default: lightweight "dummy" hash vectors (no network, tiny memory)
# - Optional: local Sentence-Transformers CPU model ("st" backend)
# - Optional: OpenAI embeddings ("openai" backend)
#
# Backend selection:
#   RAG_EMBED_BACKEND=dummy   -> tiny hash vectors (default, safest for WSL)
#   RAG_EMBED_BACKEND=st      -> SentenceTransformer("all-MiniLM-L6-v2")
#   RAG_EMBED_BACKEND=openai  -> OpenAI "text-embedding-3-small" (needs OPENAI_API_KEY)
#
# Chat/completions for Ask-Flask are unchanged; this only affects the mini-RAG module.

import os
import hashlib
from typing import List, Iterable, Any

import numpy as np

# ---------------- Backend selection ---------------------------------------

# CHANGED: Backend selection with explicit options                          # NEW
_BACKEND = os.getenv("RAG_EMBED_BACKEND", "dummy").lower()  # "dummy" | "st" | "openai"

_OPENAI_MODEL = "text-embedding-3-small"  # when using OpenAI embeddings    # NEW
_ST_MODEL = "all-MiniLM-L6-v2"            # when using SentenceTransformer   # NEW
_DUMMY_DIM = 32                           # tiny dimension for hash vectors  # NEW

# Determine which heavy backends are actually enabled
_USE_OPENAI = _BACKEND == "openai" and bool(os.getenv("OPENAI_API_KEY"))    # NEW
_USE_ST = _BACKEND == "st"                                                  # NEW

# We'll track which backend is *actually* active so model_name() can report it.
_ACTIVE_BACKEND = "dummy"                                                   # NEW default

if _USE_OPENAI:
    from openai import OpenAI  # lazy heavy import only when needed         # NEW
    _client = OpenAI()
    _ACTIVE_BACKEND = "openai"
elif _USE_ST:
    # Only pull in sentence-transformers when explicitly requested          # NEW
    from sentence_transformers import SentenceTransformer
    _st = SentenceTransformer(_ST_MODEL)
    _ACTIVE_BACKEND = "st"
else:
    # "dummy" backend: no heavy imports at all                              # NEW
    _ACTIVE_BACKEND = "dummy"


# ---------------- Helpers -------------------------------------------------

def model_name() -> str:
    """Return the active embedding model name (for logging / debug)."""
    if _ACTIVE_BACKEND == "openai":
        return _OPENAI_MODEL
    if _ACTIVE_BACKEND == "st":
        return _ST_MODEL
    # "dummy" backend
    return f"dummy-{_DUMMY_DIM}-hash"


def _normalize_texts(texts: Any) -> List[str]:
    """
    Normalize inputs to a clean List[str] for the embeddings backends.

    - Accept a single string or an iterable of items.
    - Cast non-str items to str.
    - Strip whitespace and drop empty/None entries.
    """
    # Single string → wrap in list
    if isinstance(texts, str):
        raw_list = [texts]
    else:
        if isinstance(texts, Iterable):
            try:
                raw_list = list(texts)
            except TypeError:
                raw_list = [texts]  # fallback to single-item list
        else:
            raw_list = [texts]

    cleaned: List[str] = []
    for item in raw_list:
        if item is None:
            continue
        if not isinstance(item, str):
            item = str(item)
        s = item.strip()
        if s:
            cleaned.append(s)

    return cleaned


def _dummy_hash_vector(text: str, dim: int = _DUMMY_DIM) -> np.ndarray:
    """
    Extremely lightweight, deterministic hash-based embedding.

    - Tokenizes on whitespace.
    - For each token, hashes via SHA256 and buckets into a fixed-size vector.
    - L2-normalizes the result.

    This is *not* semantically strong, but it's perfect for local dev and tests,
    and uses almost no memory or CPU.
    """
    v = np.zeros(dim, dtype=np.float32)
    for tok in text.lower().split():
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        v[idx] += 1.0
    norm = float(np.linalg.norm(v))
    if norm > 0.0:
        v /= norm
    return v


# ---------------- Main embedding function --------------------------------

def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Embed a batch of texts and return an L2-normalized numpy array.

    Backends:
      - dummy  : fast hash vectors, no heavy deps (default)
      - st     : SentenceTransformer("all-MiniLM-L6-v2")
      - openai : OpenAI "text-embedding-3-small"
    """
    # Normalize to a proper List[str]
    norm_texts = _normalize_texts(texts)

    # If everything was empty/whitespace, return a safe dummy vector instead of raising
    if not norm_texts:
        # 1 x 1 zero vector (will be treated as "no-op" by callers)
        return np.zeros((1, 1), dtype=np.float32)

    # ---- OpenAI backend ---------------------------------------------------
    if _ACTIVE_BACKEND == "openai":
        resp = _client.embeddings.create(model=_OPENAI_MODEL, input=norm_texts)
        X = np.array([d.embedding for d in resp.data], dtype=np.float32)
        norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
        return X / norms

    # ---- Sentence-Transformers backend -----------------------------------
    if _ACTIVE_BACKEND == "st":
        X = _st.encode(
            norm_texts,
            batch_size=32,
            normalize_embeddings=False,
            convert_to_numpy=True,
        ).astype(np.float32)
        norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
        return X / norms

    # ---- Dummy hash backend (default) ------------------------------------
    # Very small memory footprint; perfect for WSL/local dev.
    mats = np.stack([_dummy_hash_vector(t, _DUMMY_DIM) for t in norm_texts], axis=0)
    return mats
