"""Real sockets: uvicorn in a thread, httpx streaming, genuine mid-stream disconnects.

TestClient buffers whole responses, so it cannot prove that tokens arrive
incrementally, that heartbeats cross the wire, or that a dropped TCP connection
is survivable. These tests can.
"""
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from app.api.guard import GuardMiddleware
from app.streaming.routes import build_router
from app.streaming.store import StreamSettings, StreamStore, simulate_tokens
from tests.sse import assemble, parse_frame, stored

HEARTBEAT = 0.1
TTL = 1.0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    store = StreamStore(StreamSettings(ttl_seconds=TTL, heartbeat_seconds=HEARTBEAT, reap_interval_seconds=0.05, max_subscribers=4))
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_):
        await store.start()
        yield
        await store.close()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(GuardMiddleware, rate_limit=10_000, global_limit=10_000)
    app.include_router(build_router(store))
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.02)
    assert srv.started
    yield f"http://127.0.0.1:{port}", store
    srv.should_exit = True
    thread.join(5)


def new_stream(base, **kw):
    body = {"prompt": "live", "max_tokens": 20, "token_delay_ms": 30, **kw}
    r = httpx.post(base + "/v1/streams", json=body)
    assert r.status_code == 201, r.text
    return r.json()["stream_id"]


def read_frames(base, sid, *, after=None, stop_after_ids=None, via="header", timeout=10):
    """Read frames from a real connection; drop the connection after `stop_after_ids` id-bearing frames."""
    url = f"{base}/v1/streams/{sid}/events"
    headers, params = {}, {}
    if after is not None:
        (headers if via == "header" else params).update({"Last-Event-ID": str(after)} if via == "header" else {"last_event_id": str(after)})
    frames, ids = [], 0
    with httpx.stream("GET", url, headers=headers, params=params, timeout=timeout) as r:
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/event-stream")
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                f = parse_frame(block)
                if f:
                    frames.append(f)
                    if f.id is not None:
                        ids += 1
                    if stop_after_ids and ids >= stop_after_ids:
                        return frames  # leaving the with-block closes the socket mid-stream
    return frames


def test_tokens_arrive_incrementally_through_the_guard_middleware(server):
    base, _ = server
    sid = new_stream(base, max_tokens=10, token_delay_ms=100)  # ~1 s total
    t0 = time.monotonic()
    first_at = None
    with httpx.stream("GET", f"{base}/v1/streams/{sid}/events", timeout=10) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if first_at is None and "event: token" in buf:
                first_at = time.monotonic() - t0
    total = time.monotonic() - t0
    assert first_at < 0.5 < 0.8 < total, (first_at, total)  # not buffered until the end


def test_real_disconnect_then_resume_equals_uninterrupted_stream(server):
    base, store = server
    sid = new_stream(base, max_tokens=25, token_delay_ms=15)
    seen = []
    cuts = [4, 3, 6, 5]  # several drops at awkward places, including mid-production
    for cut in cuts:
        seen += stored(read_frames(base, sid, after=seen[-1].id if seen else None, stop_after_ids=cut))
    seen += stored(read_frames(base, sid, after=seen[-1].id))
    assert [f.id for f in seen] == list(range(1, 27))
    assert assemble(seen) == "".join(simulate_tokens("live", None, 25))
    assert seen[-1].event == "done"
    # Reference: a fresh, never-interrupted read of the stored stream is identical.
    ref = stored(read_frames(base, sid))
    assert [(f.id, f.event, f.data) for f in seen] == [(f.id, f.event, f.data) for f in ref]


def test_server_releases_connection_slots_after_client_drops(server):
    base, store = server
    sid = new_stream(base, max_tokens=60, token_delay_ms=20)
    read_frames(base, sid, stop_after_ids=2)
    stream = store.get(sid)
    for _ in range(100):
        if stream.subscribers == 0:
            break
        time.sleep(0.02)
    assert stream.subscribers == 0
    httpx.post(f"{base}/v1/streams/{sid}/cancel")


def test_resume_via_query_param_on_real_connection(server):
    base, _ = server
    sid = new_stream(base, max_tokens=8, token_delay_ms=0)
    time.sleep(0.2)
    tail = stored(read_frames(base, sid, after=6, via="query"))
    assert [f.id for f in tail] == [7, 8, 9]


def test_heartbeats_cross_the_wire_during_slow_generation_without_changing_ids(server):
    base, _ = server
    sid = new_stream(base, max_tokens=4, token_delay_ms=250)  # 2.5x the heartbeat interval per token
    frames = read_frames(base, sid)
    beats = [f for f in frames if f.event == "heartbeat"]
    assert len(beats) >= 4, [f.event for f in frames]
    assert all(b.id is None for b in beats)
    assert [f.id for f in stored(frames)] == [1, 2, 3, 4, 5]
    assert frames[0].event == "ready" and frames[0].retry == 1000
    assert frames[-1].event == "done"


def test_resume_across_heartbeats_keeps_exact_position(server):
    base, _ = server
    sid = new_stream(base, max_tokens=6, token_delay_ms=200)
    first = read_frames(base, sid, stop_after_ids=2)
    assert any(f.event == "heartbeat" for f in first)  # idle gaps already produced beats
    seen = stored(first)
    rest = stored(read_frames(base, sid, after=seen[-1].id))  # last id comes from tokens, never from a beat
    assert [f.id for f in seen + rest] == list(range(1, 8))


def test_stored_stream_expires_over_real_time_and_is_reaped(server):
    base, store = server
    sid = new_stream(base, max_tokens=3, token_delay_ms=0)
    time.sleep(0.2)
    assert httpx.get(f"{base}/v1/streams/{sid}").json()["status"] == "done"
    assert len(stored(read_frames(base, sid, after=1))) == 3  # still replayable inside the window
    time.sleep(TTL + 0.3)
    r = httpx.get(f"{base}/v1/streams/{sid}/events", headers={"Last-Event-ID": "1"})
    assert r.status_code == 410
    assert sid not in store._streams  # actually freed by the reaper
    assert httpx.get(f"{base}/v1/streams/never-existed").status_code == 404


def test_stream_in_progress_survives_longer_than_ttl(server):
    base, _ = server
    sid = new_stream(base, max_tokens=14, token_delay_ms=150)  # ~2.1 s of production > TTL of 1 s
    frames = stored(read_frames(base, sid))
    assert [f.id for f in frames] == list(range(1, 16)) and frames[-1].event == "done"


def test_heartbeats_keep_a_silent_link_alive_before_the_first_token(server):
    base, _ = server
    sid = new_stream(base, max_tokens=2, token_delay_ms=0, first_token_delay_ms=550)
    t0 = time.monotonic()
    frames = read_frames(base, sid)
    beats = [f for f in frames if f.event == "heartbeat"]
    assert len(beats) >= 4 and all(b.data["last_id"] == 0 for b in beats)
    assert time.monotonic() - t0 > 0.5
    assert [f.id for f in stored(frames)] == [1, 2, 3]
