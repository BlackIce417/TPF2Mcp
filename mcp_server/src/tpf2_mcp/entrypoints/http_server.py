"""Shared Streamable HTTP transport for the TPF2 MCP server."""
from __future__ import annotations

import asyncio
import hmac
import os
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tpf2_mcp.mcp.server import _bridge, _error, handle
from tpf2_mcp.common.audit import start_audit


PROTOCOL_VERSION = "2025-03-26"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
_bridge_client = _bridge()
_request_lock = threading.RLock()
start_audit()


def _headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }


def _authorized(request: Request) -> bool:
    token = os.environ.get("TPF2_MCP_HTTP_TOKEN")
    if not token:
        return True
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(supplied, token)


def _dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    with _request_lock:
        return handle(message, _bridge_client)


def create_http_app() -> FastAPI:
    app = FastAPI(
        title="TPF2 MCP HTTP",
        version="0.4.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version", "Mcp-Session-Id"],
        expose_headers=["MCP-Protocol-Version"],
    )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "server": "tpf2-mcp",
            "version": "0.4.0",
            "transport": "streamable-http",
            "endpoint": "/mcp",
        }, headers=_headers())

    @app.get("/mcp")
    async def mcp_get() -> Response:
        # This server is stateless and does not expose a server-initiated SSE
        # stream. Streamable HTTP clients use POST; GET is optional by spec.
        return JSONResponse(
            {"error": "METHOD_NOT_ALLOWED", "detail": "Use POST /mcp"},
            status_code=405,
            headers={**_headers(), "Allow": "POST"},
        )

    @app.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        if not _authorized(request):
            return JSONResponse(
                {"error": "UNAUTHORIZED"}, status_code=401,
                headers={**_headers(), "WWW-Authenticate": "Bearer"},
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return JSONResponse(
                {"error": "UNSUPPORTED_MEDIA_TYPE", "detail": "Content-Type must be application/json"},
                status_code=415, headers=_headers(),
            )
        raw_length = request.headers.get("content-length")
        try:
            if raw_length is not None and int(raw_length) > MAX_REQUEST_BYTES:
                return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413, headers=_headers())
        except ValueError:
            return JSONResponse({"error": "INVALID_CONTENT_LENGTH"}, status_code=400, headers=_headers())
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413, headers=_headers())
        try:
            import json
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            return JSONResponse(_error(-32700, "parse error"), status_code=400, headers=_headers())

        messages = payload if isinstance(payload, list) else [payload]
        if not messages or any(not isinstance(item, dict) for item in messages):
            return JSONResponse(_error(-32600, "invalid request"), status_code=400, headers=_headers())
        responses = []
        for message in messages:
            response = await asyncio.to_thread(_dispatch, message)
            if response is not None:
                responses.append(response)
        if not responses:
            return Response(status_code=202, headers=_headers())
        result: Any = responses if isinstance(payload, list) else responses[0]
        return JSONResponse(result, status_code=200, headers=_headers())

    return app


app = create_http_app()
