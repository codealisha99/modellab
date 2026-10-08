"""Resumable token streams.

Design
------
* A stream is produced by a background task that is *independent of any HTTP
  connection*. Clients can disconnect and reconnect without stopping it.
* Every produced event is appended to an in-memory replay buffer. Event ids are
  the 1-based position in that buffer (1, 2, 3, ...), so resuming after id N is
  exactly ``events[N:]``: no gaps, no duplicates, same order every time.
* Heartbeats are a transport concern. They are never stored and never carry an
  SSE ``id``, so they cannot move a client's ``Last-Event-ID``.
* Finished streams stay replayable for ``ttl_seconds`` (fixed, not sliding) and
  are then dropped. A bounded tombstone list lets the API answer 410 Gone for an
  expired id and 404 for an id that never existed.

Tokens are **simulated**: deterministic words derived from the prompt. No model
is called. Every token event says so (``"simulated": true``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

WORDS = (
    "model train data tune loss rank adapter layer weight batch step eval "
    "token prompt context memory recall score base tuned held-out split "
    "checkpoint gradient epoch signal result honest delta cost run".split()
)

TERMINAL_STATUSES = ("done", "cancelled")


class StreamNotFound(Exception):
    """The id was never issued (or its tombstone was evicted)."""


class StreamExpired(Exception):
    """The id existed but its retention window has passed."""


class StoreFull(Exception):
    """Too many stored or running streams."""


class TooManySubscribers(Exception):
    """Per-stream connection cap reached."""


class BadResumePoint(ValueError):
    """Last-Event-ID is malformed or ahead of what the stream has emitted."""


@dataclass(frozen=True)
class StreamSettings:
    ttl_seconds: float = 300.0
    heartbeat_seconds: float = 10.0
    max_streams: int = 256
    max_active: int = 32
    max_subscribers: int = 8
    max_tokens: int = 512
    max_delay_ms: int = 250
    max_first_token_delay_ms: int = 60_000
    reap_interval_seconds: float = 15.0
    retry_ms: int = 1000

    @classmethod
    def from_env(cls) -> "StreamSettings":
        d = cls()

        def num(name: str, default, cast):
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            value = cast(raw)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            return value

        return cls(
            ttl_seconds=num("STREAM_TTL_SECONDS", d.ttl_seconds, float),
            heartbeat_seconds=num("STREAM_HEARTBEAT_SECONDS", d.heartbeat_seconds, float),
            max_streams=num("STREAM_MAX_STORED", d.max_streams, int),
            max_active=num("STREAM_MAX_ACTIVE", d.max_active, int),
            max_subscribers=num("STREAM_MAX_SUBSCRIBERS", d.max_subscribers, int),
        )


@dataclass(frozen=True)
class Event:
    id: int
    type: str  # "token" | "done" | "cancelled"
    data: dict[str, Any]


def simulate_tokens(prompt: str, model_id: str | None, count: int) -> list[str]:
    """Deterministic fake tokens. Same (prompt, model_id, count) -> same tokens."""
    seed = hashlib.sha256(f"{model_id or 'base'}\x00{prompt}".encode()).digest()
    rng = random.Random(seed)
    out: list[str] = []
    start_of_sentence = True
    for i in range(count):
        word = rng.choice(WORDS)
        if start_of_sentence:
            word = word.capitalize()
        out.append(word if i == 0 else " " + word)
        start_of_sentence = False
        # Sentence break roughly every 8-ish tokens; punctuation is its own token.
        if i < count - 1 and rng.random() < 0.12:
            out.append(".")
            start_of_sentence = True
    return out[:count]


def text_digest(tokens: list[str]) -> str:
    return hashlib.sha256("".join(tokens).encode()).hexdigest()


def format_sse(*, event: str, data: dict[str, Any], event_id: int | None = None, retry: int | None = None) -> bytes:
    lines = []
    if retry is not None:
        lines.append(f"retry: {retry}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    # json.dumps never emits raw newlines, so one data line is always sufficient.
    lines.append("data: " + json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(lines) + "\n\n").encode()


def parse_resume_point(header: str | None, query: str | None) -> int:
    """Return the last event id the client has seen (0 = start). Header wins over query."""
    raw = header if header not in (None, "") else query
    if raw in (None, ""):
        return 0
    raw = raw.strip()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 9:
        raise BadResumePoint("Last-Event-ID must be a non-negative integer.")
    return int(raw)


@dataclass
class Stream:
    id: str
    model_id: str | None
    prompt_chars: int
    max_tokens: int
    delay: float
    first_token_delay: float
    created_at: float
    events: list[Event] = field(default_factory=list)
    status: str = "running"
    finished_at: float | None = None
    expires_at: float | None = None
    subscribers: int = 0
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def last_event_id(self) -> int:
        return len(self.events)

    async def _append(self, event_type: str, data: dict[str, Any]) -> Event:
        async with self.cond:
            ev = Event(len(self.events) + 1, event_type, data)
            self.events.append(ev)
            self.cond.notify_all()
            return ev


class StreamStore:
    def __init__(self, settings: StreamSettings | None = None, clock: Callable[[], float] = time.monotonic):
        self.settings = settings or StreamSettings()
        self.clock = clock
        self._streams: dict[str, Stream] = {}
        self._tombstones: OrderedDict[str, float] = OrderedDict()
        self._reaper: asyncio.Task | None = None

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_forever(), name="stream-reaper")

    async def close(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            await asyncio.gather(self._reaper, return_exceptions=True)
            self._reaper = None
        tasks = [s.task for s in self._streams.values() if s.task and not s.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reap_interval_seconds)
            self.sweep()

    # ---- expiry ----------------------------------------------------------

    def sweep(self) -> int:
        """Drop every stream whose retention window has passed. Returns count dropped."""
        now = self.clock()
        expired = [sid for sid, s in self._streams.items() if s.expires_at is not None and s.expires_at <= now]
        for sid in expired:
            del self._streams[sid]
            self._tombstones[sid] = now
        while len(self._tombstones) > 1024:
            self._tombstones.popitem(last=False)
        return len(expired)

    def stored_count(self) -> int:
        self.sweep()
        return len(self._streams)

    def active_count(self) -> int:
        return sum(1 for s in self._streams.values() if not s.terminal)

    # ---- create / get ----------------------------------------------------

    async def create(self, prompt: str, model_id: str | None, max_tokens: int, delay_ms: int, first_token_delay_ms: int = 0) -> Stream:
        s = self.settings
        if (not 1 <= max_tokens <= s.max_tokens or not 0 <= delay_ms <= s.max_delay_ms
                or not 0 <= first_token_delay_ms <= s.max_first_token_delay_ms):
            raise ValueError("max_tokens, token_delay_ms or first_token_delay_ms out of range")
        self.sweep()
        if len(self._streams) >= s.max_streams or self.active_count() >= s.max_active:
            raise StoreFull("Stream store is full. Try again shortly.")
        stream = Stream(
            id=secrets.token_urlsafe(16),
            model_id=model_id,
            prompt_chars=len(prompt),
            max_tokens=max_tokens,
            delay=delay_ms / 1000,
            first_token_delay=first_token_delay_ms / 1000,
            created_at=self.clock(),
        )
        self._streams[stream.id] = stream
        tokens = simulate_tokens(prompt, model_id, max_tokens)
        stream.task = asyncio.create_task(self._produce(stream, tokens), name=f"stream-{stream.id}")
        return stream

    def get(self, stream_id: str) -> Stream:
        self.sweep()
        stream = self._streams.get(stream_id)
        if stream is not None:
            return stream
        if stream_id in self._tombstones:
            raise StreamExpired(stream_id)
        raise StreamNotFound(stream_id)

    def seconds_until_expiry(self, stream: Stream) -> float | None:
        if stream.expires_at is None:
            return None
        return max(0.0, stream.expires_at - self.clock())

    # ---- producer --------------------------------------------------------

    async def _produce(self, stream: Stream, tokens: list[str]) -> None:
        if stream.first_token_delay:
            await asyncio.sleep(stream.first_token_delay)  # simulated time-to-first-token: the link is idle
        for i, tok in enumerate(tokens, 1):
            if stream.delay:
                await asyncio.sleep(stream.delay)
            await stream._append("token", {"i": i, "token": tok, "simulated": True})
        await self._finish(stream, "done")

    async def _finish(self, stream: Stream, status: str) -> None:
        async with stream.cond:
            if stream.terminal:
                return
            sent = [e.data["token"] for e in stream.events if e.type == "token"]
            data = {"total_tokens": len(sent), "sha256": text_digest(sent), "simulated": True}
            # Terminal event is appended inline so status and event land atomically.
            ev = Event(len(stream.events) + 1, status, data)
            stream.events.append(ev)
            stream.status = status
            stream.finished_at = self.clock()
            stream.expires_at = stream.finished_at + self.settings.ttl_seconds
            stream.cond.notify_all()

    async def cancel(self, stream: Stream) -> bool:
        """Stop a running stream. Returns False if it had already finished.

        The terminal ``cancelled`` event is written here, not in the producer, so it
        is produced even if the producer task had not started running yet.
        """
        if stream.terminal:
            return False
        if stream.task is not None:
            stream.task.cancel()
            await asyncio.wait([stream.task])
        await self._finish(stream, "cancelled")
        return stream.status == "cancelled"

    # ---- consumer --------------------------------------------------------

    def check_can_subscribe(self, stream: Stream, after: int) -> None:
        """Pre-flight checks the HTTP layer runs *before* it commits to a 200 response."""
        if after > stream.last_event_id:
            raise BadResumePoint("Last-Event-ID is ahead of the stream; it was never issued.")
        if stream.subscribers >= self.settings.max_subscribers:
            raise TooManySubscribers()

    def is_complete_after(self, stream: Stream, after: int) -> bool:
        """True when the client has already seen the terminal event."""
        return stream.terminal and after >= stream.last_event_id

    async def subscribe(self, stream: Stream, after: int = 0) -> AsyncIterator[bytes]:
        """Yield SSE frames for events with id > ``after`` and then follow live.

        Ends after the terminal event. While idle, emits a heartbeat every
        ``heartbeat_seconds``. Heartbeats have no ``id``.
        """
        self.check_can_subscribe(stream, after)
        stream.subscribers += 1
        try:
            yield format_sse(
                event="ready",
                data={"stream_id": stream.id, "resumed_after": after, "status": stream.status, "simulated": True},
                retry=self.settings.retry_ms,
            )
            cursor = after
            while True:
                # ids are positions, so the unseen suffix is exactly events[cursor:].
                pending = stream.events[cursor:]
                for ev in pending:
                    yield format_sse(event=ev.type, data=ev.data, event_id=ev.id)
                    cursor = ev.id
                if stream.terminal and cursor >= stream.last_event_id:
                    return
                try:
                    async with stream.cond:
                        # Predicate is checked under the lock, so a notify between the
                        # check above and the wait below cannot be lost.
                        await asyncio.wait_for(
                            stream.cond.wait_for(lambda: len(stream.events) > cursor),
                            timeout=self.settings.heartbeat_seconds,
                        )
                except TimeoutError:
                    yield format_sse(event="heartbeat", data={"last_id": cursor, "status": stream.status})
        finally:
            stream.subscribers -= 1
