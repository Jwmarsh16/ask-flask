# server/services/rag/embeddings.py
# Embeddings backend for RAG:
# - Default: local Sentence-Transformers CPU model (all-MiniLM-L6-v2)
# - Optional: OpenAI embeddings when RAG_EMBED_BACKEND=openai and OPENAI_API_KEY is set

import os
import numpy as np
from typing import List, Iterable, Any

# CHANGED: Backend selection is now controlled by RAG_EMBED_BACKEND      # explain new env
#   - "st" (default) → local SentenceTransformer
#   - "openai"       → OpenAI embeddings backend (requires OPENAI_API_KEY)
_BACKEND = os.getenv("RAG_EMBED_BACKEND", "st").lower()  # CHANGED: new env-based switch

# CHANGED: Only use OpenAI when explicitly requested AND key present      # avoid surprise kills
_USE_OPENAI = _BACKEND == "openai" and bool(os.getenv("OPENAI_API_KEY"))  # CHANGED

# CHANGED: Separate model names for clarity                               # clearer reporting
_OPENAI_MODEL = "text-embedding-3-small"  # small, fast, cheap (when OpenAI is used)  # CHANGED
_ST_MODEL = "all-MiniLM-L6-v2"            # local CPU model for default RAG backend    # CHANGED

if _USE_OPENAI:
    # Uses your existing OpenAI API key (for RAG embeddings only)         # clarify OpenAI usage
    from openai import OpenAI
    _client = OpenAI()
else:
    # Default: local SentenceTransformer backend (already installed)      # prefer stable local path
    from sentence_transformers import SentenceTransformer
    _st = SentenceTransformer(_ST_MODEL)  # CHANGED: use constant name


def model_name() -> str:
    """Return the active embedding model name (for logging / debug)."""
    # CHANGED: Report which backend is actually active                    # helps RAG debugging
    return _OPENAI_MODEL if _USE_OPENAI else _ST_MODEL


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
                raw_list = [texts]  # fallback to single-item list         # preserve robustness
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


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Embed a batch of texts and return an L2-normalized numpy array.

    - Uses OpenAI when RAG_EMBED_BACKEND=openai and OPENAI_API_KEY is set.
    - Otherwise uses the local SentenceTransformer backend.
    - Returns a (N, D) float32 matrix with unit-length rows.
    """
    # Normalize to a proper List[str]
    norm_texts = _normalize_texts(texts)

    # If everything was empty/whitespace, return a safe dummy vector instead of raising
    if not norm_texts:
        # 1 x 1 zero vector (will be treated as "no-op" by callers)        # keep previous guard
        return np.zeros((1, 1), dtype=np.float32)

    if _USE_OPENAI:
        # CHANGED: use _OPENAI_MODEL name                                  # keep config in one place
        resp = _client.embeddings.create(model=_OPENAI_MODEL, input=norm_texts)
        X = np.array([d.embedding for d in resp.data], dtype=np.float32)
    else:
        # Local CPU encode (no network, stable under low-memory / WSL)     # main stability fix
        X = _st.encode(
            norm_texts,
            batch_size=32,
            normalize_embeddings=False,
            convert_to_numpy=True,
        ).astype(np.float32)

    # L2-normalize so inner product ≈ cosine similarity
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X / norms
