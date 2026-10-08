"""Store-level verification: resume correctness, heartbeats, expiry, limits.

No HTTP here: the SSE generator is driven directly so disconnects are exact.
"""
import asyncio
import hashlib

import pytest

from app.streaming.store import (
    BadResumePoint,
    StoreFull,
    StreamExpired,
    StreamNotFound,
    StreamSettings,
    StreamStore,
    TooManySubscribers,
    parse_resume_point,
    simulate_tokens,
    text_digest,
)
from tests.sse import assemble, parse_frame, stored


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_store(**overrides):
    clock = FakeClock()
    base = dict(ttl_seconds=60, heartbeat_seconds=5, max_streams=50, max_active=50, max_subscribers=3)
    base.update(overrides)
    return StreamStore(StreamSettings(**base), clock=clock), clock


async def drain(store, stream, after=0, limit=None):
    """Read frames until the stream ends or ``limit`` frames carrying ids were read; then disconnect."""
    frames, seen = [], 0
    gen = store.subscribe(stream, after)
    try:
        async for chunk in gen:
            frames.append(parse_frame(chunk.decode().strip("\n")))
            if frames[-1].id is not None:
                seen += 1
                if limit is not None and seen >= limit:
                    break
    finally:
        await gen.aclose()  # what Starlette does on client disconnect
    return frames


async def finished(store, prompt="resume me", n=20, delay=0):
    stream = await store.create(prompt, None, n, delay)
    await asyncio.wait([stream.task])
    return stream


# ---------------------------------------------------------------- tokens

def test_simulated_tokens_are_deterministic_and_exact_length():
    a = simulate_tokens("hello", None, 40)
    assert a == simulate_tokens("hello", None, 40)
    assert len(a) == 40
    assert a != simulate_tokens("goodbye", None, 40)
    assert a != simulate_tokens("hello", "model_x", 40)
    assert simulate_tokens("hello", None, 1) and len(simulate_tokens("hello", None, 1)) == 1


async def test_full_stream_ids_are_contiguous_and_digest_matches():
    store, _ = make_store()
    s = await finished(store, n=25)
    frames = stored(await drain(store, s))
    assert [f.id for f in frames] == list(range(1, 27))  # 25 tokens + done
    assert [f.event for f in frames] == ["token"] * 25 + ["done"]
    done = frames[-1].data
    text = assemble(frames)
    assert done["total_tokens"] == 25
    assert done["sha256"] == hashlib.sha256(text.encode()).hexdigest() == text_digest(simulate_tokens("resume me", None, 25))
    assert all(f.data["simulated"] is True for f in frames)


# ---------------------------------------------------------------- resume

@pytest.mark.parametrize("cut", range(0, 22))
async def test_resume_from_every_cut_point_reconstructs_identical_stream(cut):
    """Disconnect after `cut` events, reconnect with that id: union == uninterrupted stream."""
    store, _ = make_store()
    s = await finished(store, n=20)  # 21 events including done
    reference = stored(await drain(store, s))

    first = stored(await drain(store, s, 0, limit=cut)) if cut else []
    last_seen = first[-1].id if first else 0
    assert last_seen == cut
    second = stored(await drain(store, s, last_seen))

    combined = first + second
    assert [(f.id, f.event, f.data) for f in combined] == [(f.id, f.event, f.data) for f in reference]
    assert len({f.id for f in combined}) == len(combined)  # no duplicates


async def test_resume_while_stream_is_still_being_produced():
    store, _ = make_store()
    s = await store.create("live resume", None, 30, delay_ms=5)
    seen = []
    for _ in range(4):  # four disconnects mid-production
        seen += stored(await drain(store, s, seen[-1].id if seen else 0, limit=6))
        await asyncio.sleep(0.02)
    seen += stored(await drain(store, s, seen[-1].id))
    assert [f.id for f in seen] == list(range(1, 32))
    assert seen[-1].event == "done"
    assert text_digest([f.data["token"] for f in seen if f.event == "token"]) == seen[-1].data["sha256"]
    # The producer never stopped just because nobody was connected.
    assert s.status == "done"


async def test_resume_with_a_stale_id_replays_exactly_the_missed_suffix():
    store, _ = make_store()
    s = await finished(store, n=10)
    tail = stored(await drain(store, s, after=7))
    assert [f.id for f in tail] == [8, 9, 10, 11]


async def test_ready_frame_reports_resume_point_and_retry():
    store, _ = make_store(heartbeat_seconds=5)
    s = await finished(store, n=5)
    frames = await drain(store, s, after=3)
    assert frames[0].event == "ready"
    assert frames[0].data["resumed_after"] == 3 and frames[0].id is None and frames[0].retry == 1000


async def test_resume_point_ahead_of_stream_is_rejected_before_streaming():
    store, _ = make_store()
    s = await finished(store, n=5)  # last id = 6
    store.check_can_subscribe(s, 6)
    with pytest.raises(BadResumePoint):
        store.check_can_subscribe(s, 7)
    with pytest.raises(BadResumePoint):
        await drain(store, s, after=99)


async def test_resume_at_terminal_id_means_nothing_left():
    store, _ = make_store()
    s = await finished(store, n=5)
    assert store.is_complete_after(s, 6) and not store.is_complete_after(s, 5)
    running = await store.create("slow", None, 5, delay_ms=250)
    assert not store.is_complete_after(running, 0)
    await store.cancel(running)


def test_parse_resume_point():
    assert parse_resume_point(None, None) == 0
    assert parse_resume_point("", "") == 0
    assert parse_resume_point(None, "7") == 7
    assert parse_resume_point("3", "9") == 3  # header (what EventSource sends) wins
    assert parse_resume_point("", "9") == 9
    for bad in ("-1", "abc", "1.5", "１２", "1 2", "9999999999", "0x10"):
        with pytest.raises(BadResumePoint):
            parse_resume_point(bad, None)


# ------------------------------------------------------------- heartbeats

async def test_heartbeats_are_emitted_while_idle_and_carry_no_id():
    store, _ = make_store(heartbeat_seconds=0.03)
    s = await store.create("quiet", None, 3, delay_ms=150)  # >> heartbeat interval
    frames = await drain(store, s)
    beats = [f for f in frames if f.event == "heartbeat"]
    assert len(beats) >= 3
    assert all(b.id is None for b in beats)
    assert frames[-1].event == "done"  # nothing is sent after the terminal event
    # A heartbeat reports where the stream is, never moves it.
    assert all(0 <= b.data["last_id"] <= 4 for b in beats)
    assert [f.id for f in stored(frames)] == [1, 2, 3, 4]


async def test_heartbeats_cover_the_pause_before_the_first_token():
    """Time-to-first-token: no events exist yet, so the link would be silent without heartbeats."""
    store, _ = make_store(heartbeat_seconds=0.03)
    s = await store.create("thinking", None, 2, delay_ms=0, first_token_delay_ms=200)
    frames = await drain(store, s)
    beats = [f for f in frames if f.event == "heartbeat"]
    assert len(beats) >= 4
    assert all(b.data["last_id"] == 0 and b.id is None for b in beats[:3])  # nothing emitted yet
    assert [f.id for f in stored(frames)] == [1, 2, 3]
    # Reconnecting during the pause resumes from 0 and still gets everything.
    s2 = await store.create("thinking", None, 2, delay_ms=0, first_token_delay_ms=100)
    again = stored(await drain(store, s2, after=0))
    assert [f.id for f in again] == [1, 2, 3]


async def test_heartbeats_never_affect_resume_correctness():
    store, _ = make_store(heartbeat_seconds=0.02)
    s = await store.create("beats and resume", None, 8, delay_ms=60)
    got = []
    # Reconnect after every single event, with heartbeats interleaved on each connection.
    while not got or got[-1].event != "done":
        frames = await drain(store, s, after=got[-1].id if got else 0, limit=1)
        got += stored(frames)
    assert [f.id for f in got] == list(range(1, 10))
    assert assemble(got) == "".join(simulate_tokens("beats and resume", None, 8))


async def test_no_heartbeat_noise_when_tokens_flow_promptly():
    """Notifications wake the reader immediately; heartbeats are not what delivers tokens."""
    store, _ = make_store(heartbeat_seconds=30)
    s = await store.create("fast", None, 40, delay_ms=2)
    started = asyncio.get_running_loop().time()
    frames = await drain(store, s)
    elapsed = asyncio.get_running_loop().time() - started
    assert [f for f in frames if f.event == "heartbeat"] == []
    assert len(stored(frames)) == 41
    assert elapsed < 2  # would be ~30 s per token if wakeups were lost


async def test_late_subscriber_to_running_stream_gets_backlog_then_live_events():
    store, _ = make_store(heartbeat_seconds=30)
    s = await store.create("late", None, 20, delay_ms=10)
    await asyncio.sleep(0.08)
    assert 0 < s.last_event_id < 20
    frames = stored(await drain(store, s))
    assert [f.id for f in frames] == list(range(1, 22))


# ----------------------------------------------------------------- expiry

async def test_finished_stream_is_replayable_until_ttl_then_gone():
    store, clock = make_store(ttl_seconds=60)
    s = await finished(store, n=5)
    assert store.seconds_until_expiry(s) == 60
    clock.advance(59.9)
    assert store.get(s.id) is s
    assert len(stored(await drain(store, s, after=2))) == 4
    clock.advance(0.1)  # exactly ttl
    with pytest.raises(StreamExpired):
        store.get(s.id)
    assert store.stored_count() == 0


async def test_ttl_is_fixed_reading_does_not_extend_it():
    store, clock = make_store(ttl_seconds=60)
    s = await finished(store, n=3)
    for _ in range(5):
        clock.advance(11)
        store.get(s.id)
        await drain(store, s)
    clock.advance(6)  # 61s after finish, despite constant reads
    with pytest.raises(StreamExpired):
        store.get(s.id)


async def test_running_stream_is_not_expired_and_ttl_starts_at_completion():
    store, clock = make_store(ttl_seconds=60)
    s = await store.create("long", None, 3, delay_ms=250)
    clock.advance(10_000)  # far beyond ttl while still running
    assert store.get(s.id) is s and store.seconds_until_expiry(s) is None
    await asyncio.wait([s.task])
    assert store.seconds_until_expiry(s) == 60
    clock.advance(60)
    with pytest.raises(StreamExpired):
        store.get(s.id)


async def test_unknown_id_is_not_found_but_expired_id_is_gone():
    store, clock = make_store(ttl_seconds=1)
    s = await finished(store, n=2)
    clock.advance(2)
    with pytest.raises(StreamExpired):
        store.get(s.id)
    with pytest.raises(StreamNotFound):
        store.get("never-issued")


async def test_expiry_frees_capacity_and_memory():
    store, clock = make_store(ttl_seconds=10, max_streams=3)
    ids = [(await finished(store, f"p{i}", n=2)).id for i in range(3)]
    with pytest.raises(StoreFull):
        await store.create("overflow", None, 2, 0)
    clock.advance(10)
    assert store.sweep() == 3
    assert store._streams == {}
    await store.create("fits now", None, 2, 0)
    with pytest.raises(StreamExpired):
        store.get(ids[0])


async def test_tombstones_are_bounded():
    store, clock = make_store(ttl_seconds=1, max_streams=5000, max_active=5000)
    for i in range(1100):
        await finished(store, f"t{i}", n=1)
    clock.advance(5)
    store.sweep()
    assert len(store._tombstones) == 1024


async def test_background_reaper_drops_expired_streams_without_any_access():
    store, clock = make_store(ttl_seconds=10, reap_interval_seconds=0.01)
    s = await finished(store, n=2)
    await store.start()
    try:
        clock.advance(11)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not store._streams:
                break
        assert store._streams == {}  # removed by the reaper, not by get()/create()
    finally:
        await store.close()
    assert s.id in store._tombstones


async def test_reader_attached_at_expiry_still_finishes_its_replay():
    """Expiry removes the stream from the store; a connection already open keeps its reference."""
    store, clock = make_store(ttl_seconds=5)
    s = await finished(store, n=6)
    gen = store.subscribe(s, 0)
    first = parse_frame((await gen.__anext__()).decode().strip())  # ready frame
    clock.advance(10)
    store.sweep()
    rest = [parse_frame(c.decode().strip()) async for c in gen]
    assert [f.id for f in rest] == list(range(1, 8))
    assert first.event == "ready"


# --------------------------------------------------------- limits, cancel

async def test_active_stream_cap():
    store, _ = make_store(max_active=2)
    a = await store.create("a", None, 5, 250)
    b = await store.create("b", None, 5, 250)
    with pytest.raises(StoreFull):
        await store.create("c", None, 5, 250)
    await store.cancel(a)
    await store.create("c", None, 5, 250)  # cancelled stream no longer counts as active
    await store.close()
    assert b


async def test_create_rejects_out_of_range_values():
    store, _ = make_store()
    for args in ((0, 0), (513, 0), (5, -1), (5, 251), (5, 0, -1), (5, 0, 60_001)):
        with pytest.raises(ValueError):
            await store.create("x", None, *args)


async def test_subscriber_cap_and_release_on_disconnect():
    store, _ = make_store(max_subscribers=2)
    s = await store.create("cap", None, 5, 250)
    g1, g2 = store.subscribe(s, 0), store.subscribe(s, 0)
    await g1.__anext__(), await g2.__anext__()
    assert s.subscribers == 2
    with pytest.raises(TooManySubscribers):
        store.check_can_subscribe(s, 0)
    await g1.aclose()
    assert s.subscribers == 1
    store.check_can_subscribe(s, 0)
    await g2.aclose()
    assert s.subscribers == 0
    await store.cancel(s)


async def test_cancel_writes_a_terminal_event_that_resumes_correctly():
    store, _ = make_store()
    s = await store.create("cancel me", None, 100, delay_ms=10)
    first = stored(await drain(store, s, limit=3))
    assert await store.cancel(s) is True
    assert s.status == "cancelled" and store.seconds_until_expiry(s) == 60
    rest = stored(await drain(store, s, after=first[-1].id))
    everything = first + rest
    assert [f.id for f in everything] == list(range(1, len(everything) + 1))
    assert everything[-1].event == "cancelled"
    assert everything[-1].data["total_tokens"] == len(everything) - 1 < 100
    assert await store.cancel(s) is False  # idempotent


async def test_cancel_before_producer_has_started():
    store, _ = make_store()
    s = await store.create("instant", None, 50, delay_ms=50)
    assert await store.cancel(s) is True  # no await since create(): task never ran
    frames = stored(await drain(store, s))
    assert [f.event for f in frames][-1] == "cancelled"
    assert store.is_complete_after(s, frames[-1].id)


async def test_cancel_after_done_changes_nothing():
    store, _ = make_store()
    s = await finished(store, n=3)
    assert await store.cancel(s) is False and s.status == "done"


async def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("STREAM_TTL_SECONDS", "12.5")
    monkeypatch.setenv("STREAM_HEARTBEAT_SECONDS", "2")
    monkeypatch.setenv("STREAM_MAX_STORED", "7")
    st = StreamSettings.from_env()
    assert (st.ttl_seconds, st.heartbeat_seconds, st.max_streams) == (12.5, 2.0, 7)
    monkeypatch.setenv("STREAM_TTL_SECONDS", "0")
    with pytest.raises(ValueError):
        StreamSettings.from_env()
