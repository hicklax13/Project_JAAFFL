"""Recommendation push hub behind ``WS /recs/ws`` (scaffold change #4, plan §8.5).

Back-pressure: Recommendations are idempotent snapshots keyed by ``as_of_overall_pick`` —
only the newest matters — so each subscriber gets a size-1 queue that coalesces to the
latest frame instead of buffering. Frames are serialized once per publish, not once per
subscriber (the hub sits on the future <2 s/pick hot path). Heartbeat/reconnect policy
lands with the full wire contract in roadmap stage 6.
"""

from __future__ import annotations

import asyncio
import json

from jaaffl.domain import Recommendation

PROTOCOL_VERSION = 1
SCHEMA_VERSION = "1.0.0"


class RecsHub:
    """Fan-out of the latest Recommendation to connected overlay/dashboard sockets.

    One instance lives on ``app.state.recs_hub`` (constructed in ``create_app``); the
    stage-5 engine publishes through that handle.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue[str], asyncio.AbstractEventLoop] = {}
        self._latest: Recommendation | None = None

    @property
    def latest(self) -> Recommendation | None:
        return self._latest

    def reset(self) -> None:
        """Forget the latest rec (new draft session); subscribers stay connected."""
        self._latest = None

    def subscribe(self) -> asyncio.Queue[str]:
        """Register the calling event loop's socket; must run inside that loop."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._subscribers[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.pop(queue, None)

    def publish(self, recommendation: Recommendation) -> None:
        """Thread-safe: callable from ingest handlers or (stage 5) the engine."""
        self._latest = recommendation
        frame = json.dumps(
            {
                "type": "rec",
                "v": PROTOCOL_VERSION,
                "recommendation": recommendation.model_dump(),
            }
        )
        for queue, loop in list(self._subscribers.items()):
            loop.call_soon_threadsafe(self._coalesce, queue, frame)

    @staticmethod
    def _coalesce(queue: asyncio.Queue[str], frame: str) -> None:
        if queue.full():
            queue.get_nowait()  # newest snapshot fully supersedes the stale frame
        queue.put_nowait(frame)
