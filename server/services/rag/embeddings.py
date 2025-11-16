# server/services/rag/embeddings.py
# Lightweight embeddings backend:
# - If OPENAI_API_KEY is set: use OpenAI "text-embedding-3-small".
# - Otherwise: use a tiny deterministic hash-based embedding (32-dim) with NumPy only.
#
# This avoids loading heavy local models (like sentence-transformers) so it
# won't blow up RAM inside WSL on an 8 GB laptop.

import os
import hashlib
from typing import List, Iterable, Any

import numpy as np
from dotenv import load_dotenv  # NEW: ensure .env is loaded even in ad-hoc scripts

# ----- Load .env from common locations (root + server) ---------------------
_here = os.path.abspath(os.path.dirname(__file__))              # .../server/services/rag
_server_dir = os.path.abspath(os.path.join(_here, "..", ".."))  # .../server
_root_dir = os.path.abspath(os.path.join(_server_dir, ".."))    # .../

# Try root and server .env files; don't override existing env vars
for candidate in (
    os.path.join(_root_dir, ".env"),
    os.path.join(_server_dir, ".env"),
    ".env",
):
    load_dotenv(candidate, override=False)
# ---------------------------------------------------------------------------

# If your OPENAI_API_KEY is set, we use OpenAI; otherwise we fall back to a tiny hash embedder.
_USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
_OPENAI_MODEL = "text-embedding-3-small"
_DUMMY_DIM = 32  # small, cheap vectors for local dev / tests


if _USE_OPENAI:
    # Only import the OpenAI client when we actually need it.
    from openai import OpenAI  # type: ignore[import-not-found]

    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # uses .env
else:
    _client = None  # type: ignore[assignment]


def model_name() -> str:
    """Return the name of the current embedding backend/model."""
    return _OPENAI_MODEL if _USE_OPENAI else f"dummy-{_DUMMY_DIM}-hash"


def _normalize_texts(texts: Any) -> List[str]:
    """
    Normalize inputs to a clean List[str] for the embeddings backends.

    - Accept a single string or an iterable of items.
    - Cast non-str items to str.
    - Strip whitespace and drop empty/None entries.
    """
    if isinstance(texts, str):
        raw_list = [texts]
    else:
        if isinstance(texts, Iterable):
            try:
                raw_list = list(texts)
            except TypeError:
                raw_list = [texts]
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


def _hash_to_vec(text: str, dim: int = _DUMMY_DIM) -> np.ndarray:
    """
    Very small, deterministic embedding using SHA-256 hashing.

    This is NOT semantic, but it is:
    - deterministic across runs
    - cheap in RAM/CPU
    - sufficient for testing the RAG plumbing on low-resource machines
    """
    # Hash the text to a byte buffer
    h = hashlib.sha256(text.encode("utf-8")).digest()

    # We want dim * 4 bytes (uint32) worth of data
    needed = dim * 4
    buf = (h * ((needed // len(h)) + 1))[:needed]  # repeat digest until we have enough bytes

    ints = np.frombuffer(buf, dtype=np.uint32)
    vec = ints.astype(np.float32)

    # Zero-mean, unit-ish variance to keep scales reasonable
    vec -= vec.mean()
    std = float(vec.std()) or 1.0
    vec /= std
    return vec


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Embed a batch of texts into a 2D numpy array (n_samples x dim).

    - If OPENAI_API_KEY is available, call OpenAI embeddings.
    - Otherwise, use the tiny hash-based dummy backend.
    """
    norm_texts = _normalize_texts(texts)

    # If everything was empty/whitespace, return a safe dummy vector.
    if not norm_texts:
        return np.zeros((1, 1), dtype=np.float32)

    if _USE_OPENAI and _client is not None:
        # Remote, semantic embeddings via OpenAI (cheap in local RAM).
        resp = _client.embeddings.create(model=_OPENAI_MODEL, input=norm_texts)
        X = np.array([d.embedding for d in resp.data], dtype=np.float32)
    else:
        # Ultra-lightweight local fallback: hashing only.
        vecs = [_hash_to_vec(t) for t in norm_texts]
        X = np.stack(vecs, axis=0).astype(np.float32)

    # L2-normalize so inner product ≈ cosine similarity.
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X / norms
