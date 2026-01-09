# server/services/rag/vector_store.py
# File-backed FAISS store + JSON sidecar metadata, saved under server/instance/*.

import json
import os
from typing import Dict, List, Tuple

import faiss  # FAISS CPU
import numpy as np

INSTANCE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)  # ensure instance dir exists
INDEX_PATH = os.path.join(INSTANCE_DIR, "rag_index.faiss")
META_PATH = os.path.join(INSTANCE_DIR, "rag_meta.json")


class FaissStore:
    def __init__(self, dim: int | None = None):
        self.index = None
        self.meta: List[Dict] = []
        self.dim = dim

    def load_or_init(self, dim: int):
        """
        Load index/metadata if present and dimension matches, else init new IP index.
        This makes switching embedding backends (different dimensions) safe.
        """
        self.dim = dim
        if os.path.exists(INDEX_PATH) and os.path.exists(META_PATH):
            idx = faiss.read_index(INDEX_PATH)
            # CHANGED: If stored index dim doesn't match current dim, re-init   # NEW
            if idx.d != dim:
                # Dimension changed (e.g., switching from OpenAI → dummy-32)    # NEW
                self.index = faiss.IndexFlatIP(dim)
                self.meta = []
            else:
                self.index = idx
                with open(META_PATH, "r", encoding="utf-8") as f:
                    self.meta = json.load(f)
        else:
            self.index = faiss.IndexFlatIP(
                dim
            )  # cosine via inner product (vecs are normalized)
            self.meta = []

    def add(self, vecs: np.ndarray, metas: List[Dict]):
        if self.index is None:
            raise RuntimeError("Index not initialized")
        if vecs.shape[1] != self.dim:
            raise ValueError("Embedding dim mismatch")
        self.index.add(vecs)  # add vectors
        self.meta.extend(metas)  # append metadata

    def search(self, qv: np.ndarray, pool: int = 25) -> Tuple[np.ndarray, np.ndarray]:
        """Return top `pool` candidates (scores, indices) for a single query vector."""
        if self.index is None:
            raise RuntimeError("Index not initialized")  # defensive guard       # NEW
        distances, idxs = self.index.search(qv, min(pool, self.index.ntotal))
        return distances, idxs

    def save(self):
        if self.index is None:
            raise RuntimeError("Index not initialized")  # defensive guard       # NEW
        faiss.write_index(self.index, INDEX_PATH)  # persist index
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)  # persist metadata
