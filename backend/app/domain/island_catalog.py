from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.islands import DEFAULT_VERSION, FixtureError, IslandSet, get_islands


@dataclass(frozen=True)
class IslandPublication:
    fixture_version: str
    inserted_islands: int
    inserted_fixtures: int
    unchanged_fixtures: int


class IslandCatalog(Protocol):
    """岛屿目录 seam：调用方不感知数据来自文件还是 MySQL。"""

    def list_islands(self, version: str = DEFAULT_VERSION) -> IslandSet: ...

    def publish(self, version: str = DEFAULT_VERSION) -> IslandPublication: ...

    def check_ready(self, version: str = DEFAULT_VERSION) -> bool: ...

    def close(self) -> None: ...


class FixtureIslandCatalog:
    """无数据库开发模式下的只读 Adapter。"""

    def list_islands(self, version: str = DEFAULT_VERSION) -> IslandSet:
        return get_islands(version)

    def publish(self, version: str = DEFAULT_VERSION) -> IslandPublication:
        snapshot = get_islands(version)
        return IslandPublication(
            fixture_version=snapshot.fixture_version,
            inserted_islands=0,
            inserted_fixtures=0,
            unchanged_fixtures=len(snapshot.islands),
        )

    def check_ready(self, version: str = DEFAULT_VERSION) -> bool:
        try:
            return bool(get_islands(version).islands)
        except (FixtureError, OSError, ValueError):
            return False

    def close(self) -> None:
        return None
