"""HTTP-level checks of the real app: routes, resume headers, status codes, guard."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.guard import GuardMiddleware
from app.api.main import app as main_app
from app.streaming.routes import build_router
from app.streaming.store import StreamSettings, StreamStore, simulate_tokens
from tests.sse import assemble, parse_stream, stored
from tests.test_streaming_store import FakeClock


@pytest.fixture
def env():
    """An isolated app with a fake clock so expiry is exact."""
    clock = FakeClock()
    store = StreamStore(StreamSettings(ttl_seconds=60, heartbeat_seconds=5, max_streams=4, max_active=4, max_subscribers=2), clock=clock)
    app = FastAPI()
    app.add_middleware(GuardMiddleware, rate_limit=1000, global_limit=1000)
    app.include_router(build_router(store, lambda m: m == "model_known"))
    with TestClient(app) as client:  # one event loop for the whole test so producers keep running
        yield client, store, clock


def create(client, **body):
    body.setdefault("prompt", "hello world")
    body.setdefault("max_tokens", 12)
    body.setdefault("token_delay_ms", 0)
    r = client.post("/v1/streams", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def wait_done(client, sid):
    for _ in range(200):
        if client.get(f"/v1/streams/{sid}").json()["status"] != "running":
            return
        import time; time.sleep(0.01)
    raise AssertionError("stream did not finish")


def test_create_returns_metadata_and_marks_tokens_simulated(env):
    client, *_ = env
    meta = create(client)
    assert meta["simulated"] is True and meta["status"] in ("running", "done")
    assert meta["events_url"] == f"/v1/streams/{meta['stream_id']}/events"
    assert meta["ttl_seconds"] == 60 and meta["heartbeat_seconds"] == 5


def test_full_stream_over_http(env):
    client, *_ = env
    sid = create(client)["stream_id"]
    r = client.get(f"/v1/streams/{sid}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-accel-buffering"] == "no"
    frames = stored(parse_stream(r.content))
    assert [f.id for f in frames] == list(range(1, 14))
    assert assemble(frames) == "".join(simulate_tokens("hello world", None, 12))


def test_last_event_id_header_resumes(env):
    client, *_ = env
    sid = create(client)["stream_id"]
    full = stored(parse_stream(client.get(f"/v1/streams/{sid}/events").content))
    for cut in range(0, 13):  # 13 = terminal id, covered by the 204 test
        tail = stored(parse_stream(client.get(f"/v1/streams/{sid}/events", headers={"Last-Event-ID": str(cut)}).content))
        assert [f.id for f in full[:cut]] + [f.id for f in tail] == list(range(1, 14))
        assert [f.data for f in tail] == [f.data for f in full[cut:]]


def test_query_param_resume_and_header_precedence(env):
    client, *_ = env
    sid = create(client)["stream_id"]
    wait_done(client, sid)
    by_query = stored(parse_stream(client.get(f"/v1/streams/{sid}/events?last_event_id=10").content))
    assert [f.id for f in by_query] == [11, 12, 13]
    both = stored(parse_stream(client.get(f"/v1/streams/{sid}/events?last_event_id=10", headers={"Last-Event-ID": "12"}).content))
    assert [f.id for f in both] == [13]


def test_resume_after_terminal_is_204_so_eventsource_stops(env):
    client, *_ = env
    sid = create(client)["stream_id"]
    wait_done(client, sid)
    r = client.get(f"/v1/streams/{sid}/events", headers={"Last-Event-ID": "13"})
    assert r.status_code == 204 and r.content == b""


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "99", "123456789012"])
def test_bad_resume_points_are_400_or_422_and_do_not_stream(env, value):
    client, *_ = env
    sid = create(client)["stream_id"]
    wait_done(client, sid)
    r = client.get(f"/v1/streams/{sid}/events", headers={"Last-Event-ID": value})
    assert r.status_code in (400, 422)
    assert "text/event-stream" not in r.headers["content-type"]


def test_unknown_stream_is_404_and_expired_is_410(env):
    client, store, clock = env
    assert client.get("/v1/streams/nope").status_code == 404
    assert client.get("/v1/streams/nope/events").status_code == 404
    sid = create(client)["stream_id"]
    wait_done(client, sid)
    status = client.get(f"/v1/streams/{sid}").json()
    assert status["expires_in_seconds"] == 60
    clock.advance(30)
    assert client.get(f"/v1/streams/{sid}").json()["expires_in_seconds"] == 30
    assert client.get(f"/v1/streams/{sid}/events").status_code == 200
    clock.advance(30)
    for path in (f"/v1/streams/{sid}", f"/v1/streams/{sid}/events", f"/v1/streams/{sid}/cancel"):
        r = client.post(path) if path.endswith("cancel") else client.get(path)
        assert r.status_code == 410, path
    assert "expired" in r.json()["detail"].lower()
    assert client.get(f"/v1/streams/{sid}/events", headers={"Last-Event-ID": "5"}).status_code == 410


def test_cancel_endpoint(env):
    client, *_ = env
    sid = create(client, max_tokens=300, token_delay_ms=20)["stream_id"]
    r = client.post(f"/v1/streams/{sid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    frames = stored(parse_stream(client.get(f"/v1/streams/{sid}/events").content))
    assert frames[-1].event == "cancelled"
    assert client.post(f"/v1/streams/{sid}/cancel").json()["status"] == "cancelled"


def test_store_full_returns_503_with_retry_after_and_expiry_frees_it(env):
    client, store, clock = env
    for i in range(4):
        wait_done(client, create(client, prompt=f"p{i}")["stream_id"])
    r = client.post("/v1/streams", json={"prompt": "overflow"})
    assert r.status_code == 503 and r.headers["retry-after"] == "10"
    clock.advance(61)
    assert client.post("/v1/streams", json={"prompt": "ok now"}).status_code == 201


def test_connection_cap_returns_429(env):
    client, store, _ = env
    sid = create(client, max_tokens=50, token_delay_ms=250)["stream_id"]
    s = store.get(sid)
    s.subscribers = 2  # two live readers
    r = client.get(f"/v1/streams/{sid}/events")
    assert r.status_code == 429 and r.headers["retry-after"] == "2"
    s.subscribers = 0
    client.post(f"/v1/streams/{sid}/cancel")


def test_request_validation_does_not_echo_prompt(env):
    client, *_ = env
    secret = "TOP-SECRET-PROMPT"
    for body in ({"prompt": secret, "max_tokens": 9999}, {"prompt": secret, "extra": 1}, {"prompt": secret, "max_tokens": "12"},
                 {"prompt": secret, "token_delay_ms": 251}, {"prompt": secret, "first_token_delay_ms": 60_001}, {"prompt": secret, "model_id": "m" * 65}):
        r = client.post("/v1/streams", json=body)
        assert r.status_code == 422
        assert secret not in r.text
    assert client.post("/v1/streams", json={"prompt": ""}).status_code == 422


def test_model_id_must_exist(env):
    client, *_ = env
    assert client.post("/v1/streams", json={"prompt": "x", "model_id": "model_missing"}).status_code == 404
    meta = create(client, model_id="model_known")
    assert meta["model_id"] == "model_known"


# -------------------------------------------------------- the real app

def test_main_app_serves_streams_and_playground():
    with TestClient(main_app) as client:
        sid = client.post("/v1/streams", json={"prompt": "main app", "max_tokens": 5, "token_delay_ms": 0}).json()["stream_id"]
        r = client.get(f"/v1/streams/{sid}/events")
        assert [f.id for f in stored(parse_stream(r.content))] == [1, 2, 3, 4, 5, 6]
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in r.headers["content-security-policy"]
        page = client.get("/")
        assert page.status_code == 200 and "text/html" in page.headers["content-type"]
        assert client.get("/static/app.js").status_code == 200


def test_main_app_model_id_uses_registry():
    with TestClient(main_app) as client:
        rec = [{"input": "a", "output": "b"} for _ in range(5)]
        did = client.post("/v1/datasets", json={"name": "d", "records": rec}).json()["dataset_id"]
        mid = client.post("/v1/training/run", json={"dataset_id": did}).json()["model_id"]
        r = client.post("/v1/streams", json={"prompt": "hi", "model_id": mid, "max_tokens": 3, "token_delay_ms": 0})
        assert r.status_code == 201 and r.json()["model_id"] == mid


# ------------------------------------------------------------------ guard

def make_guarded(**kw):
    app = FastAPI()
    app.add_middleware(GuardMiddleware, **kw)

    @app.post("/echo")
    async def echo(body: dict):
        return {"ok": True}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


def test_guard_rate_limits_posts_only():
    client = make_guarded(rate_limit=3, global_limit=100)
    assert [client.post("/echo", json={}).status_code for _ in range(3)] == [200] * 3
    r = client.post("/echo", json={})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert all(client.get("/ping").status_code == 200 for _ in range(10))  # GET/SSE are not counted


def test_guard_global_limit():
    client = make_guarded(rate_limit=100, global_limit=2)
    codes = [client.post("/echo", json={}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_guard_rejects_large_and_deep_bodies():
    client = make_guarded(max_body=1024)
    assert client.post("/echo", content=json.dumps({"a": "x" * 2000}), headers={"content-type": "application/json"}).status_code == 413
    deep = "[" * 40 + "]" * 40
    r = client.post("/echo", content=deep, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert client.post("/echo", content=b"\xff\xfe", headers={"content-type": "application/json"}).status_code == 422


def test_guard_security_headers_and_docs_csp():
    client = make_guarded()
    h = client.get("/ping").headers
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
    assert "script-src 'self'" in h["content-security-policy"] and "jsdelivr" not in h["content-security-policy"]


def test_main_docs_csp_allows_swagger_cdn():
    with TestClient(main_app) as client:
        assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]
