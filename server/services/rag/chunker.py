# server/services/rag/chunker.py
# Path: server/services/rag/chunker.py
# Simple, deterministic chunker with overlap for RAG ingest.
# Fixed infinite loop when text length < size due to non-progressing `start`.

from typing import List


def chunk_text(text: str, size: int = 350, overlap: int = 60) -> List[str]:
    """
    Split `text` into overlapping character windows.

    Rules:
      - `size` is the max length of each chunk.
      - `overlap` is how many characters from the end of one chunk
        are repeated at the start of the next.
      - Always makes forward progress and terminates, even when
        `len(text) < size`.

    Examples:
      len(text) == 171, size=350, overlap=60  -> 1 chunk
      len(text) == 1000, size=350, overlap=60 -> ~3 chunks
    """
    # Basic validation to avoid bad configs
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be >= 0 and < size")

    t = " ".join(text.split())  # normalize whitespace
    n = len(t)
    if n == 0:
        return []

    chunks: List[str] = []
    start = 0
    stride = size - overlap  # how far we move forward each step

    while start < n:
        end = min(n, start + size)
        chunks.append(t[start:end])

        # If we hit the end of the string, we are done
        if end == n:
            break

        # Move forward by stride so we always make progress
        start += stride

    return chunks
