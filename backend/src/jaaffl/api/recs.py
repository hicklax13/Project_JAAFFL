"""Recommendation push hub behind ``WS /recs/ws`` (scaffold change #4, plan §8.5).

Back-pressure: Recommendations are idempotent snapshots keyed by ``as_of_overall_pick`` —
only the newest matters — so each subscriber gets a size-1 queue that coalesces to the
latest frame instead of buffering. Heartbeat/reconnect policy lands with the full wire
contract in roadmap stage 6.
"""

from __future__ import annotations

import asyncio

from jaaffl.domain import Recommendation

PROTOCOL_VERSION = 1
SCHEMA_VERSION = "1.0.0"


class RecsHub:
    """Fan-out of the latest Recommendation to connected overlay/dashboard sockets."""

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue[Recommendation], asyncio.AbstractEventLoop] = {}
        self._latest: Recommendation | None = None

    @property
    def latest(self) -> Recommendation | None:
        return self._latest

    def reset(self) -> None:
        """Forget the latest rec (new draft session); subscribers stay connected."""
        self._latest = None

    def subscribe(self) -> asyncio.Queue[Recommendation]:
        """Register the calling event loop's socket; must run inside that loop."""
        queue: asyncio.Queue[Recommendation] = asyncio.Queue(maxsize=1)
        self._subscribers[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Recommendation]) -> None:
        self._subscribers.pop(queue, None)

    def publish(self, recommendation: Recommendation) -> None:
        """Thread-safe: callable from ingest handlers or (stage 5) the engine."""
        self._latest = recommendation
        for queue, loop in list(self._subscribers.items()):
            loop.call_soon_threadsafe(self._coalesce, queue, recommendation)

    @staticmethod
    def _coalesce(queue: asyncio.Queue[Recommendation], recommendation: Recommendation) -> None:
        if queue.full():
            queue.get_nowait()  # newest snapshot fully supersedes the stale frame
        queue.put_nowait(recommendation)


recs_hub = RecsHub()
