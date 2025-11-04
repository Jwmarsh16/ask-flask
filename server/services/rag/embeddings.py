# server/services/rag/embeddings.py
# Path: server/services/rag/embeddings.py
# Embeddings backend: OpenAI if API key present, else Sentence-Transformers CPU model.

import os
import numpy as np
from typing import List

_USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))  # switch based on env
_EMB_MODEL = "text-embedding-3-small"  # small, fast, cheap (when OpenAI is used)

if _USE_OPENAI:
    from openai import OpenAI  # uses your existing OpenAI API key
    _client = OpenAI()
else:
    from sentence_transformers import SentenceTransformer  # local CPU fallback
    _st = SentenceTransformer("all-MiniLM-L6-v2")

def model_name() -> str:
    return _EMB_MODEL if _USE_OPENAI else "all-MiniLM-L6-v2"

def embed_texts(texts: List[str]) -> np.ndarray:
    if _USE_OPENAI:
        resp = _client.embeddings.create(model=_EMB_MODEL, input=texts)
        X = np.array([d.embedding for d in resp.data], dtype=np.float32)
    else:
        X = _st.encode(
            texts, batch_size=32, normalize_embeddings=False, convert_to_numpy=True
        ).astype(np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X / norms  # L2-normalize so inner product = cosine
