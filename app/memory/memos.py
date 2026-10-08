"""MemOS — working/episodic/semantic memory with scoring, compression, eviction.

Everything is tenant-scoped (reads, dedup, caps, compression) and bounded, because the
service is public and in-process. All access goes through ``_LOCK``: FastAPI runs the sync
endpoints on a thread pool.
"""
import hashlib
import math
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

# In-memory stores
WORKING: List[Dict[str, Any]] = []
EPISODIC: List[Dict[str, Any]] = []
SEMANTIC: List[Dict[str, Any]] = []

WORKING_PER_TENANT = 20      # the PRD's working-memory cap, applied per tenant
WORKING_TOTAL = 500
EPISODIC_TOTAL = 5000        # oldest entries are dropped first
SEMANTIC_TOTAL = 2000
EVAL_TENANT = "__eval__"

_LOCK = threading.RLock()


def _hash_vec(text: str, dim: int = 64):
    vec = [0.0] * dim
    for w in text.lower().split():
        h = int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16)
        vec[h % dim] += 1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1
    return [v / n for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0


def _trim_oldest(pool: List[Dict[str, Any]], cap: int) -> None:
    if len(pool) > cap:
        del pool[: len(pool) - cap]


def add_memory(text: str, kind: str = "episodic", importance: float = 0.5, metadata: Optional[Dict] = None, tenant_id: str = "default") -> Dict[str, Any]:
    mid = f"mem_{uuid.uuid4().hex[:8]}"
    entry = {
        "memory_id": mid,
        "tenant_id": tenant_id,
        "text": text,
        "kind": kind,
        "importance": float(importance),
        "timestamp": time.time(),
        "embedding": _hash_vec(text),
        "metadata": metadata or {},
        "provenance": metadata.get("provenance", "user") if metadata else "user",
    }
    with _LOCK:
        if kind == "working":
            WORKING.append(entry)
            mine = [m for m in WORKING if m["tenant_id"] == tenant_id]
            if len(mine) > WORKING_PER_TENANT:
                # Evict this tenant's least important entry (never someone else's).
                victim = min(mine, key=lambda m: m["importance"])
                WORKING.remove(victim)
            _trim_oldest(WORKING, WORKING_TOTAL)
        elif kind == "semantic":
            # Dedup within the tenant only: returning another tenant's entry would leak it.
            for s in SEMANTIC:
                if s["tenant_id"] == tenant_id and _cosine(s["embedding"], entry["embedding"]) > 0.95:
                    return s
            SEMANTIC.append(entry)
            _trim_oldest(SEMANTIC, SEMANTIC_TOTAL)
        else:
            EPISODIC.append(entry)
            _trim_oldest(EPISODIC, EPISODIC_TOTAL)
    return entry


def retrieve(query: str, kind: Optional[str] = None, top_k: int = 5, tenant_id: str = "default") -> List[Dict[str, Any]]:
    q_emb = _hash_vec(query)
    pools = {"working": [WORKING], "episodic": [EPISODIC], "semantic": [SEMANTIC]}.get(kind or "", [WORKING, EPISODIC, SEMANTIC])
    candidates = []
    now = time.time()
    with _LOCK:
        for pool in pools:
            for m in pool:
                if m.get("tenant_id", "default") != tenant_id:
                    continue
                rel = _cosine(q_emb, m["embedding"])
                age_h = (now - m["timestamp"]) / 3600
                recency = 1.0 / (1 + age_h / 24)
                candidates.append((m["importance"] * rel * recency, m))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s, 3), "memory": m} for s, m in candidates[: max(0, top_k)]]


def compress_working(tenant_id: str = "default") -> str:
    with _LOCK:
        mine = [w for w in WORKING if w["tenant_id"] == tenant_id]
    if not mine:
        return ""
    # naive summarization: first 12 words of each of the latest five
    return " | ".join(" ".join(w["text"].split()[:12]) for w in mine[-5:])


def evict_expired(ttl_hours: float = 24 * 7):
    now = time.time()
    with _LOCK:
        for pool in [EPISODIC, SEMANTIC]:
            # keep if important or recent
            pool[:] = [m for m in pool if (now - m["timestamp"]) / 3600 < ttl_hours or m["importance"] > 0.8]


def _purge_tenant(tenant_id: str) -> None:
    with _LOCK:
        for pool in (WORKING, EPISODIC, SEMANTIC):
            pool[:] = [m for m in pool if m["tenant_id"] != tenant_id]


def eval_relevance(n: int = 20) -> dict:
    """M11: raw cosine relevance of the top hit, not the ranking composite.

    Runs in a private tenant and removes only its own entries, so calling it never
    touches real data (it used to clear every tenant's memory).
    """
    _purge_tenant(EVAL_TENANT)
    try:
        facts = [f"Acme invoice workflow stores ledger-{i:02d} records in vault aurora production" for i in range(n)]
        for f in facts:
            add_memory(f, "semantic", importance=0.9, tenant_id=EVAL_TENANT)
        scores = []
        hits_ok = 0
        for i, f in enumerate(facts):
            query = f"Acme invoice workflow stores ledger-{i:02d} records"
            hits = retrieve(query, "semantic", top_k=3, tenant_id=EVAL_TENANT)
            if not hits:
                scores.append(0.0)
                continue
            top = hits[0]["memory"]
            scores.append(_cosine(_hash_vec(query), top["embedding"]))
            if f"ledger-{i:02d}" in top["text"]:
                hits_ok += 1
    finally:
        _purge_tenant(EVAL_TENANT)
    avg = sum(scores) / max(1, len(scores))
    return {
        "queries": n,
        "avg_relevance": round(avg, 3),
        "hit_at_1": round(hits_ok / n, 3),
        "pass": avg > 0.7,
    }


def stats(tenant_id: str | None = None):
    def _n(pool):
        if not tenant_id:
            return len(pool)
        return sum(1 for m in pool if m.get("tenant_id", "default") == tenant_id)
    with _LOCK:
        return {"working": _n(WORKING), "episodic": _n(EPISODIC), "semantic": _n(SEMANTIC)}


def clear():
    with _LOCK:
        WORKING.clear()
        EPISODIC.clear()
        SEMANTIC.clear()
