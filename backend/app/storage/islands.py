from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.domain.island_catalog import IslandPublication
from app.islands import (
    DEFAULT_VERSION,
    FixtureError,
    IslandSet,
    load_island_payload,
    parse_islands,
)

from .schema import island_fixtures, islands


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fixture_id(island_id: str, fixture_version: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"weijian:island:{island_id}:{fixture_version}"))


class MySqlIslandCatalog:
    """MySQL Adapter：发布不可变 fixture，并从持久化快照构建读取模型。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(self, version: str = DEFAULT_VERSION) -> IslandPublication:
        document = load_island_payload(version)
        snapshot = parse_islands(document)
        raw_islands = document["islands"]
        raw_by_id = {raw["island_id"]: raw for raw in raw_islands}
        try:
            fetched_at = datetime.fromisoformat(snapshot.fetched_on).replace(tzinfo=UTC)
        except ValueError as exc:
            raise FixtureError(f"fixture fetched_on 非法: {snapshot.fetched_on}") from exc

        inserted_islands = 0
        inserted_fixtures = 0
        unchanged_fixtures = 0

        with self._engine.begin() as connection:
            for island in snapshot.islands:
                raw = raw_by_id[island.island_id]
                digest = _content_hash(raw)
                existing_island = connection.execute(
                    select(islands.c.id).where(islands.c.id == island.island_id)
                ).scalar_one_or_none()
                projection = {
                    "name": island.island_name,
                    "question_title": island.source.question_title,
                    "question_url": island.source.question_url,
                    "topic_code": island.topic_code,
                    "active_fixture_version": snapshot.fixture_version,
                }
                if existing_island is None:
                    connection.execute(
                        insert(islands).values(
                            id=island.island_id,
                            created_at=datetime.now(UTC),
                            **projection,
                        )
                    )
                    inserted_islands += 1
                else:
                    connection.execute(
                        update(islands)
                        .where(islands.c.id == island.island_id)
                        .values(**projection)
                    )

                existing_hash = connection.execute(
                    select(island_fixtures.c.content_hash).where(
                        island_fixtures.c.island_id == island.island_id,
                        island_fixtures.c.fixture_version == snapshot.fixture_version,
                    )
                ).scalar_one_or_none()
                if existing_hash is not None:
                    if existing_hash != digest:
                        raise FixtureError(
                            f"{island.island_id}/{snapshot.fixture_version}: "
                            "已发布版本的内容哈希发生变化，请创建新 fixture 版本"
                        )
                    unchanged_fixtures += 1
                    continue

                connection.execute(
                    insert(island_fixtures).values(
                        id=_fixture_id(island.island_id, snapshot.fixture_version),
                        island_id=island.island_id,
                        fixture_version=snapshot.fixture_version,
                        source_payload=raw,
                        content_hash=digest,
                        fetched_at=fetched_at,
                        safety_status="accepted",
                    )
                )
                inserted_fixtures += 1

        return IslandPublication(
            fixture_version=snapshot.fixture_version,
            inserted_islands=inserted_islands,
            inserted_fixtures=inserted_fixtures,
            unchanged_fixtures=unchanged_fixtures,
        )

    def list_islands(self, version: str = DEFAULT_VERSION) -> IslandSet:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    island_fixtures.c.source_payload,
                    island_fixtures.c.fetched_at,
                )
                .select_from(
                    islands.join(
                        island_fixtures,
                        (island_fixtures.c.island_id == islands.c.id)
                        & (
                            island_fixtures.c.fixture_version
                            == islands.c.active_fixture_version
                        ),
                    )
                )
                .where(islands.c.active_fixture_version == version)
            ).mappings().all()
        if not rows:
            raise FixtureError(f"数据库尚未发布岛屿 fixture: {version}")
        fetched_on = min(row["fetched_at"] for row in rows).date().isoformat()
        return parse_islands(
            {
                "fixture_version": version,
                "fetched_on": fetched_on,
                "islands": [row["source_payload"] for row in rows],
            }
        )

    def check_ready(self, version: str = DEFAULT_VERSION) -> bool:
        try:
            expected_document = load_island_payload(version)
            expected_hashes = {
                raw["island_id"]: _content_hash(raw)
                for raw in expected_document["islands"]
            }
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(
                        island_fixtures.c.island_id,
                        island_fixtures.c.content_hash,
                    )
                    .select_from(
                        islands.join(
                            island_fixtures,
                            (island_fixtures.c.island_id == islands.c.id)
                            & (
                                island_fixtures.c.fixture_version
                                == islands.c.active_fixture_version
                            ),
                        )
                    )
                    .where(islands.c.active_fixture_version == version)
                ).all()
            actual_hashes = {row.island_id: row.content_hash for row in rows}
            return actual_hashes == expected_hashes
        except (FixtureError, SQLAlchemyError, OSError, ValueError, KeyError, TypeError):
            return False

    def close(self) -> None:
        self._engine.dispose()
