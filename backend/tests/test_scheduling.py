from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.domain.experience import DEMO_USER_ID, ExperienceModule
from app.domain.models import TickCommand, TriggerType
from app.scheduling.scheduler import (
    InMemoryWorldScheduler,
    RedisWorldScheduler,
    tick_job_id,
)
from app.scheduling.serialization import deserialize_job, serialize_job
from app.worker import execute_world_tick, schedule_world_ticks


def test_job_id_is_stable_across_producers():
    manual = TickCommand(
        user_id="user-1",
        trigger_type=TriggerType.MANUAL,
        idempotency_key="same-window",
    )
    cron = manual.model_copy(update={"trigger_type": TriggerType.CRON})
    assert tick_job_id(manual) == tick_job_id(manual.model_copy())
    assert tick_job_id(manual) != tick_job_id(cron)
    assert "user-1" not in tick_job_id(manual)


def test_in_memory_scheduler_exposes_completed_job():
    experience = ExperienceModule()
    experience.bootstrap_demo()
    scheduler = InMemoryWorldScheduler(experience)
    command = TickCommand(
        user_id=DEMO_USER_ID,
        trigger_type=TriggerType.MANUAL,
        idempotency_key="scheduler-test",
    )

    submission = asyncio.run(scheduler.submit(command))
    fetched = asyncio.run(scheduler.get(submission.job_id))
    assert submission.status == "completed"
    assert fetched.tick and fetched.tick.id == submission.tick.id


def test_worker_executes_the_same_world_tick_interface():
    experience = ExperienceModule()
    experience.bootstrap_demo()
    payload = TickCommand(
        user_id=DEMO_USER_ID,
        trigger_type=TriggerType.MANUAL,
        idempotency_key="worker-test",
    ).model_dump(mode="json")
    result = asyncio.run(execute_world_tick({"experience": experience}, payload))
    assert result["trigger_type"] == "manual"
    assert result["idempotency_key"] == "worker-test"


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def test_redis_scheduler_enqueues_named_json_job():
    redis = _FakeRedis()
    scheduler = RedisWorldScheduler(
        redis_url="redis://127.0.0.1:6379/0",
        queue_name="weijian:ticks",
        redis=redis,
    )
    command = TickCommand(
        user_id="user-1",
        trigger_type=TriggerType.MANUAL,
        idempotency_key="manual-1",
    )
    submission = asyncio.run(scheduler.submit(command))
    args, kwargs = redis.calls[0]
    assert submission.status == "queued"
    assert args == ("execute_world_tick", command.model_dump(mode="json"))
    assert kwargs["_job_id"] == tick_job_id(command)
    assert kwargs["_queue_name"] == "weijian:ticks"


class _CronExperience:
    def list_tick_candidates(self, *, limit: int = 1000) -> tuple[str, ...]:
        assert limit == 1000
        return ("user-a", "user-b")


class _CapturingScheduler:
    def __init__(self) -> None:
        self.commands: list[TickCommand] = []

    async def submit(self, command: TickCommand):
        self.commands.append(command)


def test_cron_dispatches_candidates_through_shared_scheduler():
    scheduler = _CapturingScheduler()
    count = asyncio.run(
        schedule_world_ticks(
            {
                "experience": _CronExperience(),
                "scheduler": scheduler,
                "settings": Settings(tick_cron_minutes=10),
            }
        )
    )
    assert count == 2
    assert [command.user_id for command in scheduler.commands] == ["user-a", "user-b"]
    assert {command.trigger_type for command in scheduler.commands} == {TriggerType.CRON}
    assert len({command.idempotency_key for command in scheduler.commands}) == 1


def test_arq_serializer_is_json_not_pickle():
    payload = {"f": "execute_world_tick", "a": [{"user_id": "用户"}], "t": 1}
    encoded = serialize_job(payload)
    assert encoded.startswith(b"{")
    assert deserialize_job(encoded) == payload
