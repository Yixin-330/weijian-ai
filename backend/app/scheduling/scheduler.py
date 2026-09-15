from __future__ import annotations

import asyncio
from hashlib import sha256

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.jobs import Job, JobStatus

from app.domain.interface import Experience
from app.domain.models import TickCommand, TickSubmission, WorldTick

from .serialization import deserialize_job, serialize_job


def tick_job_id(command: TickCommand) -> str:
    digest = sha256(
        (
            f"{command.user_id}\x1f{command.trigger_type.value}"
            f"\x1f{command.idempotency_key}"
        ).encode("utf-8")
    ).hexdigest()
    return f"wj-tick-{digest}"


class InMemoryWorldScheduler:
    """Immediate Adapter used when Redis is not configured."""

    def __init__(self, experience: Experience) -> None:
        self._experience = experience
        self._jobs: dict[str, TickSubmission] = {}
        self._lock = asyncio.Lock()

    async def submit(self, command: TickCommand) -> TickSubmission:
        job_id = tick_job_id(command)
        async with self._lock:
            existing = self._jobs.get(job_id)
            if existing:
                return existing
            tick = await asyncio.to_thread(
                self._experience.run_world_tick,
                user_id=command.user_id,
                trigger_type=command.trigger_type,
                idempotency_key=command.idempotency_key,
            )
            submission = TickSubmission(job_id=job_id, status="completed", tick=tick)
            self._jobs[job_id] = submission
            return submission

    async def get(self, job_id: str) -> TickSubmission:
        return self._jobs.get(
            job_id,
            TickSubmission(job_id=job_id, status="not_found"),
        )

    async def check_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class RedisWorldScheduler:
    """arq Adapter with lazy Redis connection creation and stable job IDs."""

    def __init__(
        self,
        *,
        redis_url: str,
        queue_name: str,
        redis: ArqRedis | None = None,
    ) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._queue_name = queue_name
        self._redis = redis
        self._owns_pool = redis is None
        self._pool_lock = asyncio.Lock()

    async def submit(self, command: TickCommand) -> TickSubmission:
        redis = await self._get_pool()
        job_id = tick_job_id(command)
        job = await redis.enqueue_job(
            "execute_world_tick",
            command.model_dump(mode="json"),
            _job_id=job_id,
            _queue_name=self._queue_name,
            _expires=86_400,
        )
        if job is None:
            return await self.get(job_id)
        return TickSubmission(job_id=job_id, status="queued")

    async def get(self, job_id: str) -> TickSubmission:
        redis = await self._get_pool()
        job = Job(
            job_id,
            redis=redis,
            _queue_name=self._queue_name,
            _deserializer=deserialize_job,
        )
        job_status = await job.status()
        if job_status is JobStatus.not_found:
            return TickSubmission(job_id=job_id, status="not_found")
        if job_status in {JobStatus.queued, JobStatus.deferred}:
            return TickSubmission(job_id=job_id, status="queued")
        if job_status is JobStatus.in_progress:
            return TickSubmission(job_id=job_id, status="in_progress")

        result_info = await job.result_info()
        if result_info is None:
            return TickSubmission(job_id=job_id, status="not_found")
        if not result_info.success:
            return TickSubmission(
                job_id=job_id,
                status="failed",
                error="tick execution failed",
            )
        tick = WorldTick.model_validate(result_info.result)
        return TickSubmission(job_id=job_id, status="completed", tick=tick)

    async def check_ready(self) -> bool:
        try:
            redis = await self._get_pool()
            return bool(await redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self._redis is not None and self._owns_pool:
            await self._redis.aclose(close_connection_pool=True)
            self._redis = None

    async def _get_pool(self) -> ArqRedis:
        if self._redis is not None:
            return self._redis
        async with self._pool_lock:
            if self._redis is None:
                self._redis = await create_pool(
                    self._redis_settings,
                    retry=0,
                    job_serializer=serialize_job,
                    job_deserializer=deserialize_job,
                    default_queue_name=self._queue_name,
                )
        return self._redis
