# server/services/rag/chunker.py
# Path: server/services/rag/chunker.py
# Simple, deterministic chunker with overlap for RAG ingest.

from typing import List

def chunk_text(text: str, size: int = 350, overlap: int = 60) -> List[str]:
    t = " ".join(text.split())  # normalize whitespace
    chunks, start = [], 0
    n = len(t)
    while start < n:
        end = min(n, start + size)
        chunks.append(t[start:end])  # take window
        start = max(0, end - overlap)  # step back for overlap
        if start >= n:
            break
    return chunks
