from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import build_router
from app.core.config import Settings
from app.core.observability import TraceIdMiddleware, current_trace_id
from app.domain.errors import Conflict, DomainError, Forbidden, NotFound
from app.domain.interface import Experience
from app.domain.island_catalog import IslandCatalog
from app.scheduling import WorldScheduler, build_world_scheduler
from app.storage import build_experience, build_island_catalog


def create_app(
    *,
    settings: Settings | None = None,
    experience: Experience | None = None,
    island_catalog: IslandCatalog | None = None,
    scheduler: WorldScheduler | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    module = experience or build_experience(resolved_settings)
    catalog = island_catalog or build_island_catalog(resolved_settings)
    world_scheduler = scheduler or build_world_scheduler(resolved_settings, module)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await world_scheduler.close()
        await asyncio.to_thread(module.close)
        await asyncio.to_thread(catalog.close)

    app = FastAPI(title="未见后端", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.experience = module
    app.state.island_catalog = catalog
    app.state.world_scheduler = world_scheduler
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Demo-Admin-Token", "X-Trace-Id"],
    )
    app.include_router(build_router(module, catalog, resolved_settings, world_scheduler))

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "application": "weijian-backend",
            "environment": resolved_settings.environment,
            "storage": "mysql" if resolved_settings.database_url else "memory",
            "queue": "redis" if resolved_settings.redis_url else "memory",
        }

    @app.get("/ready")
    async def ready(response: Response):
        storage_ready, queue_ready, islands_ready = await asyncio.gather(
            asyncio.to_thread(module.check_ready),
            world_scheduler.check_ready(),
            asyncio.to_thread(catalog.check_ready),
        )
        ready_now = storage_ready and queue_ready and islands_ready
        if not ready_now:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if ready_now else "not_ready",
            "storage": storage_ready,
            "queue": queue_ready,
            "islands": islands_ready,
        }

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        status_code = 400
        if isinstance(exc, NotFound):
            status_code = 404
        elif isinstance(exc, Conflict):
            status_code = 409
        elif isinstance(exc, Forbidden):
            status_code = 403
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc), "trace_id": current_trace_id()},
        )

    return app


app = create_app()
