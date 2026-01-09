# server/services/rag/evals.py
# Path: server/services/rag/evals.py
# Tiny eval helpers: Recall@k and latency timer.

import time
from typing import Callable, Dict, List, Tuple


def timeit(fn: Callable, *args, **kwargs) -> Tuple[float, any]:
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    dt = (time.perf_counter() - t0) * 1000.0
    return dt, out  # ms, result


def recall_at_k(hits: List[Dict], expected_doc_id: str) -> int:
    return 1 if any(h.get("doc_id") == expected_doc_id for h in hits) else 0


def eval_suite(queries: List[Dict], retrieve_fn: Callable, k: int = 4) -> Dict:
    scores, latencies = [], []
    for item in queries:
        q, expected = item["q"], item["expected_doc_id"]
        dt, hits = timeit(retrieve_fn, q, k)
        latencies.append(dt)
        scores.append(recall_at_k(hits, expected))
    latencies.sort()
    p95 = latencies[int(max(0, 0.95 * len(latencies) - 1))] if latencies else 0.0
    return {
        "recall_at_k": sum(scores) / len(scores) if scores else 0.0,
        "p95_latency_ms": p95,
        "n": len(scores),
    }
