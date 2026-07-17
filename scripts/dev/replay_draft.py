#!/usr/bin/env python
"""Replay a fixture of DraftEvents into the ingest WebSocket (E4 regression / demo).

Usage:
    python scripts/dev/replay_draft.py <events.json> [--url ws://127.0.0.1:8788/draft/ws]
                                       [--delay 0.05] [--first N]

The fixture is a JSON array of DraftEvent objects (or JSONL, one per line) — e.g.
scripts/dev/fixtures/synthetic_draft.json, a curated record-mode capture, or any
tests/fixtures *.expected.json. Prints each ack and a summary; exits non-zero if any
event is rejected. Duplicate picks are EXPECTED to ack deduped=true (idempotent server).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def load_events(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    doc = json.loads(text)
    return doc if isinstance(doc, list) else [doc]


async def replay(events: list[dict], url: str, delay: float) -> int:
    import websockets  # bundled via uvicorn[standard]

    accepted = deduped = errors = 0
    async with websockets.connect(url) as ws:
        for event in events:
            await ws.send(json.dumps(event))
            ack = json.loads(await ws.recv())
            if ack.get("type") == "ack":
                accepted += 1
                deduped += 1 if ack.get("deduped") else 0
                flag = " (deduped)" if ack.get("deduped") else ""
                print(f"  ack seq={ack.get('seq')} pick={ack.get('pick_number')}{flag}")
            else:
                errors += 1
                print(f"  ERROR frame: {ack}")
            await asyncio.sleep(delay)
    print(f"replayed {len(events)} events: {accepted} acked ({deduped} deduped), {errors} errors")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--url", default="ws://127.0.0.1:8788/draft/ws")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--first", type=int, default=None, help="send only the first N events")
    args = parser.parse_args()
    events = load_events(args.fixture)
    if args.first is not None:
        events = events[: args.first]
    return asyncio.run(replay(events, args.url, args.delay))


if __name__ == "__main__":
    sys.exit(main())
