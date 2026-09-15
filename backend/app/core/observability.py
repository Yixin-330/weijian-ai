from __future__ import annotations

from contextvars import ContextVar, Token
import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="")


def current_trace_id() -> str:
    trace_id = trace_id_context.get()
    return trace_id or uuid4().hex


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        supplied = request.headers.get("X-Trace-Id", "")
        trace_id = supplied if _TRACE_ID_PATTERN.fullmatch(supplied) else uuid4().hex
        token: Token[str] = trace_id_context.set(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_context.reset(token)

