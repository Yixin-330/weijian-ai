from __future__ import annotations

from app.core.config import Settings
from app.domain.interface import Experience

from .interface import WorldScheduler
from .scheduler import InMemoryWorldScheduler, RedisWorldScheduler


def build_world_scheduler(settings: Settings, experience: Experience) -> WorldScheduler:
    if not settings.redis_url:
        return InMemoryWorldScheduler(experience)
    return RedisWorldScheduler(
        redis_url=settings.redis_url,
        queue_name=settings.tick_queue_name,
    )

