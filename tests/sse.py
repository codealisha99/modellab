"""Tiny SSE frame parser for tests."""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Frame:
    event: str
    data: dict
    id: int | None = None
    retry: int | None = None


def parse_frame(block: str) -> Frame | None:
    event, id_, retry, data = "message", None, None, []
    for line in block.split("\n"):
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event = value
        elif name == "id":
            id_ = int(value)
        elif name == "retry":
            retry = int(value)
        elif name == "data":
            data.append(value)
    if not data:
        return None
    return Frame(event, json.loads("\n".join(data)), id_, retry)


def parse_stream(raw: bytes | str) -> list[Frame]:
    text = raw.decode() if isinstance(raw, bytes) else raw
    return [f for f in (parse_frame(b) for b in text.split("\n\n")) if f]


def stored(frames: list[Frame]) -> list[Frame]:
    """Frames that are real stream events (carry an id), as opposed to open/heartbeat."""
    return [f for f in frames if f.id is not None]


def assemble(frames: list[Frame]) -> str:
    return "".join(f.data["token"] for f in frames if f.event == "token")
