---
name: verify
description: Verify JAAFFL backend changes by driving the real FastAPI surface — launch the server, hit REST routes, and handshake the WebSocket channels. Use after changing backend/src/jaaffl (API, config, domain contracts).
---

# Verify JAAFFL (backend surface)

## Launch

```bash
cd <repo root>
.venv/Scripts/python.exe -m jaaffl.api            # binds 127.0.0.1:8788 (default)
JAAFFL_API_PORT=8789 .venv/Scripts/python.exe -m jaaffl.api   # if 8788 is also busy
```

Gotchas:

- The default port is now **8788** (the extension + web default here too). 8787 is often held by an
  unrelated local process (seen: bun.exe) — don't kill it; the 8788 default sidesteps it. If 8788 is
  also busy, override with `JAAFFL_API_PORT`. Check with `netstat -ano | grep :8788`.
- Run from the repo root: `config/engine.json` and `.env` resolve relative to cwd.
- The venv lives at repo root (`.venv/Scripts/python.exe`); backend installed editable.

## Drive

REST (curl):

```bash
curl -s http://127.0.0.1:8788/health                          # {"status":"ok",...}
curl -s -w " [%{http_code}]" http://127.0.0.1:8788/league/x   # 404 until stage 2
curl -s -w " [%{http_code}]" "http://127.0.0.1:8788/recommendation?league_id=L1"  # 501 until stage 5
curl -s -X POST http://127.0.0.1:8788/draft/events -H "Content-Type: application/json" \
  -d '{"event_type":"pick_made","league_id":"L1","data":{"overall":1,"round":1,"pick_in_round":1,"team_id":"T3"}}'
```

WebSocket (`websockets` is in the venv via uvicorn[standard]): connect to
`ws://127.0.0.1:8788/recs/ws` and expect a `hello` frame then a `snapshot` frame
(recommendation is null until the engine lands). `/draft/ws` accepts DraftEvent JSON and
answers `{"accepted": true}` per frame. Run two /recs/ws clients concurrently to confirm
fan-out registration.

Engine tunables load at the package boundary (from repo root):

```bash
.venv/Scripts/python.exe -c "from jaaffl.config import get_engine_params; print(get_engine_params())"
```

## Known Phase-0 limits (don't file as bugs)

- `/recs/ws` only detects a client disconnect on the next send (no receive-loop /
  heartbeat until stage 6, plan §8.5) — `recs_ws_disconnected` may not log on close.
- No external path publishes recommendations until stage 5; broadcast fan-out is
  exercised via `jaaffl.api.recs.recs_hub.publish(...)` in-process (see tests/test_api.py).
