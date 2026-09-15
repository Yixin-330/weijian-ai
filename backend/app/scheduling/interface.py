from __future__ import annotations

from typing import Protocol

from app.domain.models import TickCommand, TickSubmission


class WorldScheduler(Protocol):
    """Queue seam shared by manual requests and cron dispatch."""

    async def submit(self, command: TickCommand) -> TickSubmission: ...

    async def get(self, job_id: str) -> TickSubmission: ...

    async def check_ready(self) -> bool: ...

    async def close(self) -> None: ...

