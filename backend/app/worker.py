from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings
from app.domain.interface import Experience
from app.domain.models import TickCommand, TriggerType
from app.scheduling.scheduler import RedisWorldScheduler
from app.scheduling.serialization import deserialize_job, serialize_job
from app.storage import build_experience


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = Settings.from_env()
    if not settings.database_url:
        raise RuntimeError("WJ_DATABASE_URL is required by the arq worker")
    if not settings.redis_url:
        raise RuntimeError("WJ_REDIS_URL is required by the arq worker")
    ctx["settings"] = settings
    ctx["experience"] = build_experience(settings)
    ctx["scheduler"] = RedisWorldScheduler(
        redis_url=settings.redis_url,
        queue_name=settings.tick_queue_name,
        redis=ctx["redis"],
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    experience: Experience | None = ctx.get("experience")
    if experience is not None:
        await asyncio.to_thread(experience.close)


async def execute_world_tick(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    command = TickCommand.model_validate(payload)
    experience: Experience = ctx["experience"]
    tick = await asyncio.to_thread(
        experience.run_world_tick,
        user_id=command.user_id,
        trigger_type=command.trigger_type,
        idempotency_key=command.idempotency_key,
    )
    return tick.model_dump(mode="json")


async def schedule_world_ticks(ctx: dict[str, Any]) -> int:
    experience: Experience = ctx["experience"]
    scheduler: RedisWorldScheduler = ctx["scheduler"]
    settings: Settings = ctx["settings"]
    user_ids = await asyncio.to_thread(experience.list_tick_candidates, limit=1000)
    now = datetime.now(timezone.utc)
    window = f"{now:%Y%m%d%H}{now.minute // settings.tick_cron_minutes:02d}"
    for user_id in user_ids:
        await scheduler.submit(
            TickCommand(
                user_id=user_id,
                trigger_type=TriggerType.CRON,
                idempotency_key=f"cron:{window}",
            )
        )
    return len(user_ids)


_settings = Settings.from_env()
_redis_url = _settings.redis_url or "redis://127.0.0.1:6379/0"


class WorkerSettings:
    functions = [execute_world_tick]
    cron_jobs = [
        cron(
            schedule_world_ticks,
            minute=set(range(0, 60, _settings.tick_cron_minutes)),
            second=0,
            run_at_startup=False,
            unique=True,
            max_tries=1,
        )
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(_redis_url)
    queue_name = _settings.tick_queue_name
    max_jobs = 10
    max_tries = 3
    job_timeout = 120
    keep_result = 3600
    health_check_interval = 30
    job_serializer = serialize_job
    job_deserializer = deserialize_job
