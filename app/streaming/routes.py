"""HTTP surface for resumable simulated token streams."""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .store import (
    BadResumePoint,
    Stream,
    StreamExpired,
    StreamNotFound,
    StreamStore,
    StoreFull,
    TooManySubscribers,
    parse_resume_point,
)

SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",  # stop nginx-style proxies from buffering the stream
    "Connection": "keep-alive",
}


class StreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, Field(min_length=1, max_length=2000)]
    model_id: Annotated[str | None, Field(max_length=64)] = None
    max_tokens: Annotated[int, Field(strict=True, ge=1, le=512)] = 48
    token_delay_ms: Annotated[int, Field(strict=True, ge=0, le=250)] = 40
    first_token_delay_ms: Annotated[int, Field(strict=True, ge=0, le=60_000)] = 0


def describe(store: StreamStore, s: Stream) -> dict:
    return {
        "stream_id": s.id,
        "status": s.status,
        "last_event_id": s.last_event_id,
        "max_tokens": s.max_tokens,
        "model_id": s.model_id,
        "simulated": True,
        "expires_in_seconds": store.seconds_until_expiry(s),
        "ttl_seconds": store.settings.ttl_seconds,
        "heartbeat_seconds": store.settings.heartbeat_seconds,
        "events_url": f"/v1/streams/{s.id}/events",
    }


def build_router(store: StreamStore, known_model: Callable[[str], bool] = lambda _id: True) -> APIRouter:
    router = APIRouter(prefix="/v1/streams", tags=["streaming"])

    def lookup(stream_id: str) -> Stream:
        try:
            return store.get(stream_id)
        except StreamExpired:
            raise HTTPException(410, "Stream expired. Stored streams are kept for a limited time after they finish.")
        except StreamNotFound:
            raise HTTPException(404, "Stream not found.")

    @router.post("", status_code=201)
    async def create_stream(body: StreamRequest):
        if body.model_id is not None and not known_model(body.model_id):
            raise HTTPException(404, "model not found")
        try:
            stream = await store.create(body.prompt, body.model_id, body.max_tokens, body.token_delay_ms, body.first_token_delay_ms)
        except StoreFull as exc:
            return JSONResponse({"detail": str(exc)}, 503, headers={"Retry-After": "10"})
        return describe(store, stream)

    @router.get("/{stream_id}")
    async def stream_status(stream_id: str):
        return describe(store, lookup(stream_id))

    @router.post("/{stream_id}/cancel")
    async def cancel_stream(stream_id: str):
        stream = lookup(stream_id)
        await store.cancel(stream)
        return describe(store, stream)

    @router.get(
        "/{stream_id}/events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}, 204: {}, 400: {}, 404: {}, 410: {}, 429: {}},
    )
    async def stream_events(
        request: Request,
        stream_id: str,
        last_event_id: Annotated[str | None, Query(max_length=16, description="Resume point for clients that cannot set headers.")] = None,
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID", max_length=16)] = None,
    ):
        stream = lookup(stream_id)
        try:
            after = parse_resume_point(last_event_id_header, last_event_id)
            # Everything that can fail is decided here, before a 200 is committed.
            store.check_can_subscribe(stream, after)
        except BadResumePoint as exc:
            raise HTTPException(400, str(exc))
        except TooManySubscribers:
            return JSONResponse({"detail": "Too many connections to this stream."}, 429, headers={"Retry-After": "2"})
        if store.is_complete_after(stream, after):
            # 204 tells EventSource to stop reconnecting: it already has the terminal event.
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return StreamingResponse(store.subscribe(stream, after), media_type="text/event-stream", headers=SSE_HEADERS)

    return router
