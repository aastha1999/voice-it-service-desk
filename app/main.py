"""HTTP API called by the ElevenLabs agent's server tools.

Run:  uvicorn app.main:create_app --factory --port 8000

Every response uses one envelope so the agent always has something sensible to say:
    {"ok": true,  "data": {...}, "speakable": "...", "request_id": "..."}
    {"ok": false, "error": {"code", "message", "details"}, "speakable": "...", "request_id": "..."}
"""
import hmac
import json
import logging
import time
import uuid

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import audit, services
from app.audit import RequestContext
from app.config import Settings, load_settings
from app.db import connect, init_db, transaction
from app.errors import InternalError, InvalidInput, ServiceDeskError, Unauthorized
from app.mdm import FakeMDM, MDMClient
from app.models import (CancelDeviceActionRequest, ConfirmDeviceActionRequest, CreateTicketRequest,
                        GetTicketRequest, LookupDeviceRequest, RequestDeviceActionRequest)

log = logging.getLogger("servicedesk")


def _envelope_error(request: Request, exc: ServiceDeskError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=exc.status_code, content={
        "ok": False,
        "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        "speakable": exc.speakable,
        "request_id": request_id,
    }, headers={"X-Request-ID": request_id or ""})


def create_app(settings: Settings | None = None, mdm: MDMClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db(settings.db_path)
    mdm = mdm or FakeMDM(fault=settings.mdm_fault)

    app = FastAPI(title="Voice IT Service Desk API", version="1.0.0")
    app.state.settings = settings
    app.state.mdm = mdm

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        log.info(json.dumps({"request_id": request.state.request_id, "method": request.method,
                             "path": request.url.path, "status": response.status_code,
                             "ms": round((time.perf_counter() - start) * 1000, 1)}))
        return response

    @app.exception_handler(ServiceDeskError)
    async def handle_domain_error(request: Request, exc: ServiceDeskError):
        log.warning(json.dumps({"request_id": getattr(request.state, "request_id", None),
                                "error": exc.code, "message": exc.message}))
        return _envelope_error(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]
        return _envelope_error(request, InvalidInput("Request validation failed", details={"fields": fields}))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return _envelope_error(request, InternalError("Internal error"))

    # ---------- dependencies ----------

    def get_conn():
        conn = connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _check_secret(request: Request, provided: str | None, expected: str, actor: str) -> None:
        if provided and hmac.compare_digest(provided.encode(), expected.encode()):
            return
        conn = connect(settings.db_path)
        try:
            with transaction(conn):
                audit.record(conn, RequestContext(request.state.request_id, actor="unknown"), "auth.failed",
                             target=request.url.path, scope=actor,
                             client=request.client.host if request.client else None)
        finally:
            conn.close()
        raise Unauthorized("Missing or invalid credentials")

    def require_tool_secret(request: Request, x_tool_secret: str | None = Header(default=None)):
        _check_secret(request, x_tool_secret, settings.tool_secret, "tool")

    def require_admin(request: Request, x_admin_key: str | None = Header(default=None)):
        _check_secret(request, x_admin_key, settings.admin_key, "admin")

    def ctx_for(request: Request, body) -> RequestContext:
        return RequestContext(request_id=request.state.request_id, conversation_id=body.conversation_id)

    def ok(request: Request, result: tuple[dict, str]) -> dict:
        data, speakable = result
        return {"ok": True, "data": data, "speakable": speakable, "request_id": request.state.request_id}

    tool = {"dependencies": [Depends(require_tool_secret)], "tags": ["voice agent tools"]}
    admin = {"dependencies": [Depends(require_admin)], "tags": ["admin"]}

    # ---------- routes ----------

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/tools/lookup_device", **tool)
    def lookup_device(body: LookupDeviceRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.lookup_devices(conn, ctx_for(request, body), body.email, body.asset_tag))

    @app.post("/tools/create_ticket", **tool)
    def create_ticket(body: CreateTicketRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.create_ticket(
            conn, ctx_for(request, body), device_id=body.device_id, caller_email=body.caller_email,
            summary=body.summary, category=body.category, priority=body.priority))

    @app.post("/tools/get_ticket", **tool)
    def get_ticket(body: GetTicketRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.get_ticket(conn, ctx_for(request, body), body.ticket_id))

    @app.post("/tools/request_device_action", **tool)
    def request_device_action(body: RequestDeviceActionRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.request_device_action(
            conn, ctx_for(request, body), settings, device_id=body.device_id, action=body.action,
            ticket_id=body.ticket_id, caller_email=body.caller_email))

    @app.post("/tools/confirm_device_action", **tool)
    def confirm_device_action(body: ConfirmDeviceActionRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.confirm_device_action(
            conn, ctx_for(request, body), settings, app.state.mdm,
            pending_action_id=body.pending_action_id, caller_utterance=body.caller_utterance))

    @app.post("/tools/cancel_device_action", **tool)
    def cancel_device_action(body: CancelDeviceActionRequest, request: Request, conn=Depends(get_conn)):
        return ok(request, services.cancel_device_action(conn, ctx_for(request, body),
                                                         pending_action_id=body.pending_action_id))

    @app.get("/admin/audit", **admin)
    def list_audit(conversation_id: str | None = None, limit: int = 100, conn=Depends(get_conn)):
        return {"ok": True, "data": audit.list_entries(conn, conversation_id, min(max(limit, 1), 1000))}

    @app.get("/admin/audit/verify", **admin)
    def verify_audit(conn=Depends(get_conn)):
        return {"ok": True, "data": audit.verify(conn)}

    return app

