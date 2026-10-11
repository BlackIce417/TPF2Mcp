"""FastAPI adapter for the local railway map and dispatch UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import re
from sqlite3 import Error as SQLiteError
import threading
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .bridge import BridgeError
from .dispatch_regions import current_region_view


TILE_KEY = re.compile(r"^[0-9]+_[0-9]+$")
class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControlConfigurationRequest(StrictBody):
    patch: dict[str, Any]
    confirmation: str | None = None


class EmergencyStopRequest(StrictBody):
    reason: str | None = None


class DispatchCommandRequest(StrictBody):
    command: dict[str, Any]
    confirmation: str | None = None


def _json(value: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status_code, headers={"Cache-Control": "no-store"})


def create_web_app(state: Any, *, manage_watcher: bool = False) -> FastAPI:
    """Build the Web adapter around an existing domain state object."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker = None
        if manage_watcher:
            state.stop.clear()
            worker = threading.Thread(target=state.watch, name="rail-map-watcher", daemon=True)
            worker.start()
        try:
            yield
        finally:
            state.stop.set()
            if worker is not None:
                worker.join(timeout=5)

    app = FastAPI(
        title="TPF2 Rail Map API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.rail_map = state

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json({"error": "INVALID_REQUEST", "reason": str(exc)}, 400)

    @app.middleware("http")
    async def cache_and_body_boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_length = request.headers.get("content-length")
            try:
                length = int(raw_length or "0")
            except ValueError:
                return _json({"error": "INVALID_REQUEST", "reason": "invalid Content-Length"}, 400)
            if length <= 0 or length > 1024 * 1024:
                return _json({"error": "INVALID_REQUEST", "reason": "JSON body must be 1..1048576 bytes"}, 400)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/status")
    def status():
        return _json(state.status())

    @app.get("/api/rail/manifest")
    def rail_manifest():
        return _json(state.read_json(state.root / "rail-network-manifest.json"))

    @app.get("/api/station-previews/{station_id}")
    def station_preview(station_id: str):
        if not station_id.isdigit():
            return _json({"error": "invalid station id"}, 400)
        value = state.read_json(state.root / "station-previews" / f"station-{station_id}.json")
        return _json(value, 200 if value else 404)

    @app.get("/api/regional-status")
    def regional_status():
        value = state.read_json(state.root / "regional-status.json")
        return _json(value, 200 if value else 404)

    def bridge_document(name: str):
        value = state.read_json(state.bridge / name)
        return _json(value, 200 if value else 404)

    @app.get("/api/telemetry")
    def telemetry():
        return bridge_document("operational-telemetry.json")

    @app.get("/api/live")
    def live():
        return bridge_document("live-rail-state.json")

    @app.get("/api/control")
    def control():
        return bridge_document("rail-control-state.json")

    @app.get("/api/control-system")
    def control_system():
        return _json(state.control_status())

    @app.get("/api/dispatch-platform")
    def dispatch_platform():
        return _json(state.dispatch_platform_status())

    @app.get("/api/dispatch-regions")
    def dispatch_regions():
        value = current_region_view(
            state.read_json(state.bridge / "dispatch" / "region-view.json"),
            state.current_save_id(),
            state.read_json(state.root / "rail-network-manifest.json"),
        )
        status_code = 200 if "error" not in value else (404 if value["error"] == "REGIONS_NOT_CONFIGURED" else 409)
        return _json(value, status_code)

    @app.get("/api/infrastructure-speed-profile")
    def infrastructure_speed_profile():
        return _json(state.speed_profile())

    @app.get("/api/timetable-plan")
    def timetable_plan():
        value = state.timetable_plan()
        return _json(value, 409 if value.get("error") else 200)

    @app.get("/api/timetable-live")
    def timetable_live(line_id: str = Query(default="")):
        try:
            parsed = int(line_id)
            if parsed < 0:
                raise ValueError()
        except ValueError:
            return _json({"error": "INVALID_LINE_ID"}, 400)
        return _json(state.timetable_live(parsed))

    @app.get("/api/ai-suggestions")
    def ai_suggestions():
        return _json(state.ai_suggestions())

    @app.get("/api/mcp-work-log")
    def mcp_work_log(limit: str = Query(default="30")):
        if limit.lower() == "all":
            parsed = None
        else:
            try:
                parsed = int(limit)
            except ValueError:
                return _json({"error": "invalid limit"}, 400)
        return _json(state.mcp_work_logs(parsed))

    @app.get("/api/operations-context")
    def operations_context():
        value = state.operations_context()
        return _json(value, 200 if value.get("lines") else 404)

    @app.get("/api/vehicle-detail/{vehicle_id}")
    def vehicle_detail(vehicle_id: str):
        if not vehicle_id.isdigit():
            return _json({"error": "invalid vehicle id"}, 400)
        try:
            value = state.vehicle_detail(int(vehicle_id))
        except (BridgeError, ValueError) as exc:
            return _json({"error": str(exc)}, 503)
        return _json(value, 200 if "error" not in value else 404)

    @app.get("/api/station-logs/{station_id}")
    def station_logs(station_id: str, limit: str = Query(default="100")):
        if not station_id.isdigit():
            return _json({"error": "invalid station id"}, 400)
        try:
            parsed_limit = int(limit)
        except ValueError:
            return _json({"error": "invalid limit"}, 400)
        save_id = state.current_save_id()
        rows = state.station_events.query(int(station_id), save_id, parsed_limit)
        return _json({"save_id": save_id, "station_id": int(station_id), "events": rows, "count": len(rows)})

    @app.get("/api/rail/tile/{key}")
    def rail_tile(key: str):
        if not TILE_KEY.fullmatch(key):
            return _json({"error": "invalid tile key"}, 400)
        value = state.read_json(state.root / "rail-network-tiles" / f"tile-{key}.json")
        return _json(value, 200 if value else 404)

    @app.get("/api/events")
    async def events():
        async def stream():
            last = None
            while not state.stop.is_set():
                current = state.status()
                if current != last:
                    payload = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
                    yield f"event: status\ndata: {payload}\n\n"
                    last = current
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    def record_mutation(endpoint: str, action: str, body: dict[str, Any], value: dict[str, Any], status_code: int = 200):
        try:
            state.web_store.record(
                save_id=state.current_save_id(), endpoint=endpoint, action=action,
                status_code=status_code, request=body, response=value,
            )
        except (OSError, SQLiteError, ValueError):
            # Emergency control must remain available if the audit database is
            # temporarily unavailable. The domain layer keeps its own journal.
            pass
        return _json(value, status_code)

    @app.post("/api/control-system/config")
    def configure_control(body: ControlConfigurationRequest):
        payload = body.model_dump()
        try:
            value = state.control_system.configure(body.patch, state.current_save_id(), body.confirmation)
        except ValueError as exc:
            return _json({"error": "INVALID_REQUEST", "reason": str(exc)}, 400)
        return record_mutation("/api/control-system/config", "CONFIGURE_CONTROL", payload, value)

    @app.post("/api/control-system/stop")
    def emergency_stop(body: EmergencyStopRequest):
        payload = body.model_dump()
        value = state.control_system.emergency_stop(body.reason or "USER_REQUEST")
        return record_mutation("/api/control-system/stop", "EMERGENCY_STOP", payload, value)

    @app.post("/api/dispatch-platform/commands")
    def submit_dispatch_command(body: DispatchCommandRequest):
        payload = body.model_dump()
        try:
            value = state.dispatch_platform.submit(body.command, state.current_save_id(), body.confirmation)
        except ValueError as exc:
            return _json({"error": "INVALID_REQUEST", "reason": str(exc)}, 400)
        return record_mutation("/api/dispatch-platform/commands", "SUBMIT_DISPATCH_COMMAND", payload, value)

    @app.get("/api/web/mutations")
    def web_mutations(limit: int = Query(default=100, ge=1, le=1000)):
        save_id = state.current_save_id()
        rows = state.web_store.recent(save_id, limit)
        return _json({"save_id": save_id, "count": len(rows), "entries": rows})

    return app
