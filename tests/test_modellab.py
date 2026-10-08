from fastapi.testclient import TestClient
from app.api.main import app
from app.training.pipeline import clear as clear_train
from app.memory.memos import clear as clear_mem

client = TestClient(app)

def setup_function(fn):
    clear_train()
    clear_mem()

def test_health():
    assert client.get("/health").json()["status"] == "ok"

def test_dataset_validate_endpoint():
    r = client.post("/v1/datasets/validate", json={"name": "x", "records": [{"input": "q", "output": "a"}]})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_dataset_ingest_and_split():
    records = [{"input": f"q{i}", "output": f"a{i}"} for i in range(10)]
    r = client.post("/v1/datasets", json={"name":"test","records": records})
    assert r.status_code == 200
    did = r.json()["dataset_id"]
    r2 = client.get(f"/v1/datasets/{did}").json()
    assert r2["train"] == 8
    assert r2["val"] == 2

def test_lora_training_and_eval():
    records = [{"input":"in","output":"out"} for _ in range(10)]
    did = client.post("/v1/datasets", json={"name":"d","records": records}).json()["dataset_id"]
    r = client.post("/v1/training/run", json={"dataset_id": did, "base_model":"phi-3-mini","lora_r":8})
    mid = r.json()["model_id"]
    m = client.get(f"/v1/models/{mid}").json()
    assert "checkpoints" in m
    assert len(m["checkpoints"]) == 3
    e = client.post(f"/v1/models/{mid}/evaluate").json()
    assert "base" in e and "fine_tuned" in e
    assert "justified" in e
    assert "answer" in e

def test_model_registry_and_inference():
    rec = [{"input":"a","output":"b"} for _ in range(5)]
    did = client.post("/v1/datasets", json={"name":"d2","records": rec}).json()["dataset_id"]
    mid = client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"]
    r = client.get("/v1/models").json()
    assert len(r["models"]) >= 1
    inf = client.post("/v1/inference", json={"model_id": mid, "prompt":"hello"}).json()
    assert "completion" in inf

def test_memory_tiers():
    client.post("/v1/memory", json={"text":"User prefers Java","kind":"semantic","importance":0.9})
    client.post("/v1/memory", json={"text":"User asked about RAG","kind":"episodic","importance":0.7})
    client.post("/v1/memory", json={"text":"current plan: build RAG","kind":"working","importance":0.6})
    s = client.get("/v1/memory/stats").json()
    assert s["semantic"] == 1
    assert s["episodic"] == 1
    assert s["working"] == 1

def test_memory_retrieval_scoring():
    client.post("/v1/memory", json={"text":"Project uses PostgreSQL","kind":"semantic","importance":0.9})
    client.post("/v1/memory", json={"text":"User loves cats","kind":"semantic","importance":0.2})
    r = client.get("/v1/memory/search?q=PostgreSQL").json()
    assert len(r["results"]) >= 1
    assert r["results"][0]["score"] > 0.3

def test_memory_dedup_and_eviction():
    client.post("/v1/memory", json={"text":"dup test content","kind":"semantic"})
    client.post("/v1/memory", json={"text":"dup test content","kind":"semantic"})
    s = client.get("/v1/memory/stats").json()
    assert s["semantic"] == 1  # deduped
    # working cap 20
    for i in range(25):
        client.post("/v1/memory", json={"text":f"working {i}","kind":"working","importance": i/25})
    s2 = client.get("/v1/memory/stats").json()
    assert s2["working"] == 20

def test_memory_tenant_isolation():
    client.post("/v1/memory", json={"text": "secret aurora ledger", "kind": "semantic", "importance": 0.9}, headers={"X-Tenant-Id": "tenantA"})
    a = client.get("/v1/memory/search?q=aurora", headers={"X-Tenant-Id": "tenantA"}).json()
    b = client.get("/v1/memory/search?q=aurora", headers={"X-Tenant-Id": "tenantB"}).json()
    assert len(a["results"]) >= 1
    assert a["results"][0]["memory"]["tenant_id"] == "tenantA"
    assert b["results"] == []


def test_memory_eval_suite():
    r = client.get("/v1/memory/eval").json()
    assert r["queries"] == 20
    assert r["avg_relevance"] > 0.7


def test_justified_answer():
    rec = [{"input":"a","output":"b"} for _ in range(5)]
    did = client.post("/v1/datasets", json={"name":"d3","records": rec}).json()["dataset_id"]
    mid = client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"]
    e = client.post(f"/v1/models/{mid}/evaluate").json()
    assert "Did fine-tuning" in e["answer"] or "Fine-tuning" in e["answer"]
