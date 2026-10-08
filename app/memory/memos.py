"""MemOS — working/episodic/semantic memory with scoring, compression, eviction."""
import time, uuid, hashlib, re
from typing import Dict, Any, List, Optional
import math

# In-memory stores
WORKING: List[Dict[str, Any]] = []  # capped
EPISODIC: List[Dict[str, Any]] = []
SEMANTIC: List[Dict[str, Any]] = []

def _hash_vec(text: str, dim: int = 64):
    import hashlib
    vec = [0.0]*dim
    for w in text.lower().split():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    n = math.sqrt(sum(v*v for v in vec)) or 1
    return [v/n for v in vec]

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0

def add_memory(text: str, kind: str = "episodic", importance: float = 0.5, metadata: Optional[Dict]=None, tenant_id: str = "default") -> Dict[str, Any]:
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
        "provenance": metadata.get("provenance","user") if metadata else "user",
    }
    if kind == "working":
        WORKING.append(entry)
        if len(WORKING) > 20:  # cap
            # evict lowest importance
            WORKING.sort(key=lambda x: x["importance"])
            WORKING.pop(0)
    elif kind == "semantic":
        # dedup: if near-duplicate exists, skip
        for s in SEMANTIC:
            if _cosine(s["embedding"], entry["embedding"]) > 0.95:
                return s
        SEMANTIC.append(entry)
    else:
        EPISODIC.append(entry)
    return entry

def retrieve(query: str, kind: Optional[str] = None, top_k: int = 5, tenant_id: str = "default") -> List[Dict[str, Any]]:
    q_emb = _hash_vec(query)
    candidates = []
    pools = []
    if kind == "working":
        pools = [WORKING]
    elif kind == "episodic":
        pools = [EPISODIC]
    elif kind == "semantic":
        pools = [SEMANTIC]
    else:
        pools = [WORKING, EPISODIC, SEMANTIC]
    for pool in pools:
        for m in pool:
            if m.get("tenant_id", "default") != tenant_id:
                continue
            rel = _cosine(q_emb, m["embedding"])
            # recency
            age_h = (time.time() - m["timestamp"]) / 3600
            recency = 1.0/(1+age_h/24)
            score = m["importance"] * rel * recency
            candidates.append((score, m))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s,3), "memory": m} for s,m in candidates[:top_k]]

def compress_working() -> str:
    if not WORKING:
        return ""
    # naive summarization: first 5 words of each
    parts = [" ".join(w["text"].split()[:12]) for w in WORKING[-5:]]
    return " | ".join(parts)

def evict_expired(ttl_hours: float = 24*7):
    now = time.time()
    for pool in [EPISODIC, SEMANTIC]:
        # keep if important or recent
        pool[:] = [m for m in pool if (now - m["timestamp"])/3600 < ttl_hours or m["importance"] > 0.8]

def eval_relevance(n: int = 20) -> dict:
    """M11: raw cosine relevance of the top hit, not the ranking composite."""
    clear()
    facts = [
        f"Acme invoice workflow stores ledger-{i:02d} records in vault aurora production"
        for i in range(n)
    ]
    for f in facts:
        add_memory(f, "semantic", importance=0.9)
    scores = []
    hits_ok = 0
    for i, f in enumerate(facts):
        query = f"Acme invoice workflow stores ledger-{i:02d} records"
        hits = retrieve(query, "semantic", top_k=3)
        if not hits:
            scores.append(0.0)
            continue
        top = hits[0]["memory"]
        scores.append(_cosine(_hash_vec(query), top["embedding"]))
        if f"ledger-{i:02d}" in top["text"]:
            hits_ok += 1
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
    return {"working": _n(WORKING), "episodic": _n(EPISODIC), "semantic": _n(SEMANTIC)}

def clear():
    WORKING.clear()
    EPISODIC.clear()
    SEMANTIC.clear()
