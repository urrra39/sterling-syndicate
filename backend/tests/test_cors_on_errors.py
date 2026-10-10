from __future__ import annotations

"""Guard-middleware rejections must stay readable cross-origin."""

from fastapi.testclient import TestClient

from app.core.rate_limit import reset_state
from app.main import GLOBAL_RATE_LIMIT, app

ORIGIN = "http://localhost:5173"


def test_rate_limited_response_carries_cors_headers() -> None:
    reset_state()
    client = TestClient(app)
    try:
        for _ in range(GLOBAL_RATE_LIMIT):
            client.get("/", headers={"Origin": ORIGIN})
        res = client.get("/", headers={"Origin": ORIGIN})
        assert res.status_code == 429
        assert res.headers.get("access-control-allow-origin") == ORIGIN
    finally:
        reset_state()
