"""ASGI middleware: strip guardrail meta-tags from JSON string values in responses."""

from __future__ import annotations

import json
from typing import Any, Callable, MutableMapping

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.output_sanitizer import sanitize_output


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_output(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


class OutputSanitizerMiddleware(BaseHTTPMiddleware):
    """Recursively sanitize string fields in application/json responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        if hasattr(response, "body") and isinstance(getattr(response, "body", None), (bytes, bytearray)):
            body = bytes(response.body)
        elif hasattr(response, "body_iterator"):
            async for chunk in response.body_iterator:
                body += chunk if isinstance(chunk, (bytes, bytearray)) else str(chunk).encode()
        else:
            return response

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )

        scrubbed = _scrub(payload)
        headers: MutableMapping[str, str] = {
            k: v for k, v in response.headers.items() if k.lower() != "content-length"
        }
        return JSONResponse(
            content=scrubbed,
            status_code=response.status_code,
            headers=dict(headers),
        )
