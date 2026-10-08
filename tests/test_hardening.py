"""Regression tests for bugs found in the audit: each of these failed before the fix."""
import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.memory import memos
from app.observability.otel import span
from app.streaming.store import StreamSettings, StreamStore
from app.training import pipeline
from tests.sse import parse_frame

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    pipeline.clear()
    memos.clear()
    yield
    pipeline.clear()
    memos.clear()


def make_dataset(n=10, unique=True):
    rows = [{"input": f"q{i}" if unique else "q", "output": f"a{i}" if unique else "a"} for i in range(n)]
    return client.post("/v1/datasets", json={"name": "d", "records": rows}).json()["dataset_id"]


# ------------------------------------------------------------------ tracing

def test_span_does_not_swallow_or_double_yield_on_exception():
    """Used to raise RuntimeError('generator didn't stop after throw()') -> HTTP 500."""
    with pytest.raises(ValueError, match="boom"):
        with span("t", a=1):
            raise ValueError("boom")


def test_training_on_unknown_dataset_is_404_not_500():
    r = client.post("/v1/training/run", json={"dataset_id": "nope"})
    assert r.status_code == 404 and r.json()["detail"] == "dataset not found"


# ------------------------------------------------------------------- memory

def test_memory_eval_does_not_erase_real_memory():
    """GET /v1/memory/eval used to call clear(): any visitor could wipe every tenant."""
    client.post("/v1/memory", json={"text": "keep me", "kind": "semantic"}, headers={"X-Tenant-Id": "acme"})
    client.post("/v1/memory", json={"text": "and me", "kind": "episodic"})
    before = memos.stats()
    r = client.get("/v1/memory/eval").json()
    assert r["pass"] is True and r["queries"] == 20
    assert memos.stats() == before
    assert not any(m["tenant_id"] == memos.EVAL_TENANT for pool in (memos.WORKING, memos.EPISODIC, memos.SEMANTIC) for m in pool)


def test_semantic_dedup_never_returns_another_tenants_memory():
    a = client.post("/v1/memory", json={"text": "tenant A secret ledger", "kind": "semantic"}, headers={"X-Tenant-Id": "A"}).json()
    b = client.post("/v1/memory", json={"text": "tenant A secret ledger", "kind": "semantic"}, headers={"X-Tenant-Id": "B"}).json()
    assert b["tenant_id"] == "B" and b["memory_id"] != a["memory_id"]
    again = client.post("/v1/memory", json={"text": "tenant A secret ledger", "kind": "semantic"}, headers={"X-Tenant-Id": "A"}).json()
    assert again["memory_id"] == a["memory_id"]  # dedup still works inside a tenant


def test_working_memory_cap_is_per_tenant():
    for i in range(30):
        client.post("/v1/memory", json={"text": f"noisy {i}", "kind": "working", "importance": 0.9}, headers={"X-Tenant-Id": "noisy"})
    client.post("/v1/memory", json={"text": "quiet one", "kind": "working", "importance": 0.1}, headers={"X-Tenant-Id": "quiet"})
    assert client.get("/v1/memory/stats", headers={"X-Tenant-Id": "noisy"}).json()["working"] == 20
    assert client.get("/v1/memory/stats", headers={"X-Tenant-Id": "quiet"}).json()["working"] == 1


def test_compress_and_stats_are_tenant_scoped():
    client.post("/v1/memory", json={"text": "alpha plan details", "kind": "working"}, headers={"X-Tenant-Id": "A"})
    client.post("/v1/memory", json={"text": "bravo plan details", "kind": "working"}, headers={"X-Tenant-Id": "B"})
    assert client.post("/v1/memory/compress", headers={"X-Tenant-Id": "A"}).json()["summary"] == "alpha plan details"
    assert client.post("/v1/memory/compress").json()["summary"] == ""  # default tenant has none
    assert client.get("/v1/memory/stats").json() == {"working": 0, "episodic": 0, "semantic": 0}


def test_memory_pools_are_capped_and_drop_oldest(monkeypatch):
    monkeypatch.setattr(memos, "EPISODIC_TOTAL", 5)
    monkeypatch.setattr(memos, "SEMANTIC_TOTAL", 3)
    monkeypatch.setattr(memos, "WORKING_TOTAL", 4)
    for i in range(9):
        memos.add_memory(f"episode number {i}", "episodic", tenant_id=f"t{i}")
        memos.add_memory(f"completely distinct fact {i} zebra{i}", "semantic", tenant_id=f"t{i}")
        memos.add_memory(f"work {i}", "working", tenant_id=f"t{i}")
    assert [m["text"] for m in memos.EPISODIC] == [f"episode number {i}" for i in range(4, 9)]
    assert len(memos.SEMANTIC) == 3 and len(memos.WORKING) == 4


@pytest.mark.parametrize("body", [
    {"text": "x", "importance": 99},
    {"text": "x", "importance": -0.1},
    {"text": "x", "kind": "nope"},
    {"text": ""},
    {"text": "x" * 4001},
    {"text": "x", "metadata": {"k": "v" * 3000}},
])
def test_memory_add_rejects_bad_input(body):
    assert client.post("/v1/memory", json=body).status_code == 422


@pytest.mark.parametrize("query", ["q=a&top_k=0", "q=a&top_k=-5", "q=a&top_k=100000000", "q=", "q=" + "x" * 501, "q=a&kind=nope"])
def test_memory_search_rejects_bad_input(query):
    assert client.get(f"/v1/memory/search?{query}").status_code == 422


@pytest.mark.parametrize("tenant", ["a b", "a/b", "../x", "x" * 65, b"t\xc3\xa9", memos.EVAL_TENANT])
def test_tenant_header_is_validated(tenant):
    r = client.get("/v1/memory/stats", headers={"X-Tenant-Id": tenant})
    assert r.status_code in (400, 422)


def test_valid_tenant_header_still_works():
    assert client.get("/v1/memory/stats", headers={"X-Tenant-Id": "Acme_Corp-1.eu"}).status_code == 200


# -------------------------------------------------------- training registry

@pytest.mark.parametrize("body", [
    {"lora_r": -1}, {"lora_r": 0}, {"lora_r": 257}, {"lora_r": 1.5}, {"lora_alpha": 0}, {"base_model": "bad name!"}, {"base_model": ""},
])
def test_training_rejects_bad_hyperparameters(body):
    did = make_dataset()
    assert client.post("/v1/training/run", json={"dataset_id": did, **body}).status_code == 422


@pytest.mark.parametrize("body", [{"prompt": {"a": 1}}, {"prompt": 5}, {"prompt": "x" * 4001}, {"prompt": "ok", "surprise": 1}, {"model_id": ["x"]}])
def test_inference_rejects_bad_input(body):
    assert client.post("/v1/inference", json=body).status_code == 422


def test_dataset_limits_and_dropped_rows_are_reported():
    assert client.post("/v1/datasets", json={"name": "", "records": []}).status_code == 422
    assert client.post("/v1/datasets", json={"name": "x", "records": [{"input": "a", "output": "b"}] * 5001}).status_code == 422
    rows = [{"input": "a", "output": "b"}, {"input": "", "output": "b"}, {"input": "c"}]
    v = client.post("/v1/datasets/validate", json={"name": "x", "records": rows}).json()
    assert v["valid"] is True and v["dropped"] == 2 and v["count"] == 1
    ing = client.post("/v1/datasets", json={"name": "x", "records": rows}).json()
    assert ing["count"] == 3 and ing["kept"] == 1


def test_model_views_never_expose_training_data():
    did = make_dataset()
    mid = client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"]
    for view in (client.get(f"/v1/models/{mid}").json(), client.get("/v1/models").json()["models"][0]):
        assert "lookup" not in view and "val_rows" not in view
        assert view["model_id"] == mid


def test_registries_are_bounded_and_old_checkpoints_are_deleted(monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "MAX_MODELS", 2)
    monkeypatch.setattr(pipeline, "MAX_DATASETS", 1)
    mids = []
    for _ in range(4):
        did = make_dataset()
        mids.append(client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"])
    assert len(pipeline.DATASETS) == 1 and len(pipeline.MODELS) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(mids[-2:])  # evicted models leave no files behind
    assert client.get(f"/v1/models/{mids[0]}").status_code == 404
    # The surviving models were trained on datasets that have since been evicted; evaluation must still work.
    assert client.post(f"/v1/models/{mids[-1]}/evaluate").status_code == 200


def test_unsafe_model_ids_never_reach_rmtree(monkeypatch, tmp_path):
    victim = tmp_path / "keep"
    victim.mkdir()
    monkeypatch.setenv("CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "MAX_MODELS", 1)
    pipeline.MODELS["../keep"] = {"model_id": "../keep", "val_rows": [], "lookup": {}, "checkpoints": []}
    did = make_dataset()
    client.post("/v1/training/run", json={"dataset_id": did})
    assert victim.exists() and "../keep" not in pipeline.MODELS


def test_stream_with_trained_model_uses_registry():
    did = make_dataset()
    mid = client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"]
    with TestClient(app) as c:
        assert c.post("/v1/streams", json={"prompt": "hi", "model_id": mid, "max_tokens": 2, "token_delay_ms": 0}).status_code == 201
        assert c.post("/v1/streams", json={"prompt": "hi", "model_id": "model_unknown"}).status_code == 404


# ---------------------------------------------------------------- shutdown

async def test_begin_shutdown_ends_idle_readers_immediately():
    """With a 30 s heartbeat, a reader used to be stuck until the server's own timeout."""
    store = StreamStore(StreamSettings(heartbeat_seconds=30, ttl_seconds=60))
    s = await store.create("quiet", None, 5, delay_ms=250, first_token_delay_ms=5000)
    frames, started = [], time.monotonic()

    async def read():
        async for chunk in store.subscribe(s, 0):
            frames.append(parse_frame(chunk.decode().strip()))

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.1)
    store.begin_shutdown()
    await asyncio.wait_for(reader, timeout=2)
    assert time.monotonic() - started < 2
    assert [f.event for f in frames] == ["ready", "shutdown"]
    assert frames[-1].id is None and frames[-1].data["last_id"] == 0
    await store.close()


async def test_shutdown_still_replays_backlog_before_ending():
    store = StreamStore(StreamSettings(heartbeat_seconds=30, ttl_seconds=60))
    s = await store.create("backlog", None, 4, delay_ms=0)
    await asyncio.wait([s.task])
    store.begin_shutdown()
    got = [parse_frame(c.decode().strip()) async for c in store.subscribe(s, 2)]
    assert [f.id for f in got if f.id] == [3, 4, 5]  # a finished stream is still delivered fully
    s2 = await store.create("running", None, 50, delay_ms=250)
    got = [parse_frame(c.decode().strip()) async for c in store.subscribe(s2, 0)]
    assert got[-1].event == "shutdown"
    await store.close()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_real_server_exits_promptly_on_sigterm_with_a_client_connected():
    """The actual `python -m app.run` process: used to hang ~15 s and log a CancelledError traceback."""
    port = free_port()
    env = {**os.environ, "PORT": str(port), "OTEL_SDK_DISABLED": "true", "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    proc = subprocess.Popen([sys.executable, "-m", "app.run"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        sid = httpx.post(base + "/v1/streams", json={"prompt": "x", "max_tokens": 200, "token_delay_ms": 250}).json()["stream_id"]
        seen = []
        with httpx.stream("GET", f"{base}/v1/streams/{sid}/events", timeout=20) as r:
            it = r.iter_text()
            seen.append(next(it))  # connected and receiving
            started = time.monotonic()
            proc.send_signal(signal.SIGTERM)
            for chunk in it:
                seen.append(chunk)
            ended = time.monotonic() - started
        proc.wait(timeout=8)
        elapsed = time.monotonic() - started
        out = proc.stdout.read()
        assert "event: shutdown" in "".join(seen)
        assert ended < 3 and elapsed < 5, (ended, elapsed)
        assert "Traceback" not in out and "CancelledError" not in out, out
        assert proc.returncode in (0, -signal.SIGTERM)  # uvicorn re-raises the signal after a clean stop
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
