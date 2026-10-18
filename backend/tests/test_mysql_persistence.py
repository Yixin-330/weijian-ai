from __future__ import annotations

import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from app.core.config import Settings
from app.domain.experience import DEMO_MEMORY_ID, DEMO_USER_ID
from app.domain.island_policy import ISLAND_AI_LONELINESS, ISLAND_INTIMACY
from app.domain.island_catalog import FixtureIslandCatalog
from app.main import create_app
from app.storage.mysql import MySqlExperienceModule
from app.storage.schema import evidence, memories, metadata


def persistent_client(database_path: Path) -> tuple[TestClient, MySqlExperienceModule]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    metadata.create_all(engine)
    module = MySqlExperienceModule(engine)
    settings = Settings(
        environment="test",
        demo_admin_token="test-admin",
        database_url=str(database_path),
    )
    return TestClient(
        create_app(
            settings=settings,
            experience=module,
            island_catalog=FixtureIslandCatalog(),
        )
    ), module


def test_calibration_and_tick_survive_module_restart(tmp_path: Path):
    database_path = tmp_path / "experience.db"
    client, _ = persistent_client(database_path)
    assert client.post("/api/v1/demo/bootstrap").status_code == 200

    calibration = client.post(
        f"/api/v1/memories/{DEMO_MEMORY_ID}/calibrations",
        json={
            "user_id": DEMO_USER_ID,
            "decision": "opposes",
            "allow_social_recommendation": False,
        },
    )
    assert calibration.status_code == 200
    tick = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "persisted-tick",
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert tick.status_code == 202
    tick_id = tick.json()["tick"]["id"]
    restarted_client, _ = persistent_client(database_path)
    world = restarted_client.get(f"/api/v1/users/{DEMO_USER_ID}/world")
    assert world.status_code == 200
    assert world.json()["lifeform"]["current_island_id"] == ISLAND_INTIMACY
    assert world.json()["memories"][0]["calibration"] == "opposes"
    assert world.json()["latest_tick"]["id"] == tick_id

    duplicate = restarted_client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "persisted-tick",
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["tick"]["id"] == tick_id


def test_onboarding_survives_module_restart(tmp_path: Path):
    database_path = tmp_path / "onboarding.db"
    client, _ = persistent_client(database_path)
    payload = {
        "current_question": "亲密关系里如何保留彼此的自由和边界？",
        "long_term_topics": ["intimacy_and_autonomy"],
        "exploration_style": "observe",
        "social_pace": "shared_experiences",
        "allow_memory_inference": True,
        "allow_social_recommendation": True,
    }
    created = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "persistent-onboarding"},
        json=payload,
    )
    assert created.status_code == 201
    user_id = created.json()["user"]["id"]

    restarted_client, _ = persistent_client(database_path)
    world = restarted_client.get(f"/api/v1/users/{user_id}/world")
    assert world.status_code == 200
    assert world.json()["source_mode"] == "live"
    assert world.json()["lifeform"]["current_island_id"] == ISLAND_INTIMACY
    assert len(world.json()["memories"]) == 2

    retry = restarted_client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "persistent-onboarding"},
        json=payload,
    )
    assert retry.status_code == 201
    assert retry.json()["user"]["id"] == user_id


def test_alembic_revision_covers_every_versioned_mysql_table():
    backend_root = Path(__file__).parents[1]
    revision_path = backend_root / "migrations" / "versions" / "0001_core.py"
    spec = spec_from_file_location("migration_0001_core", revision_path)
    assert spec and spec.loader
    revision = module_from_spec(spec)
    spec.loader.exec_module(revision)

    statements = revision.migration_statements()
    table_names = tuple(
        match.group(1)
        for statement in statements
        if (match := re.search(r"CREATE TABLE IF NOT EXISTS ([a-z_]+)", statement))
    )
    assert table_names == revision.TABLES_IN_DEPENDENCY_ORDER
    assert len(statements) == len(table_names) + 1  # SET NAMES plus one statement per table


def test_materialized_ai_topic_can_reach_third_island(tmp_path: Path):
    database_path = tmp_path / "ai-topic.db"
    client, _ = persistent_client(database_path)
    assert client.post("/api/v1/demo/bootstrap").status_code == 200

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
                update(memories)
                .where(memories.c.id == DEMO_MEMORY_ID)
                .values(topic_code="ai_and_loneliness", score=0.98)
        )
    engine.dispose()

    response = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "ai-topic-tick",
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert response.status_code == 202
    assert response.json()["tick"]["selected_island_id"] == ISLAND_AI_LONELINESS


def test_fixture_encounter_and_relationship_survive_restart(tmp_path: Path):
    database_path = tmp_path / "encounter.db"
    client, _ = persistent_client(database_path)
    assert client.post("/api/v1/demo/bootstrap").status_code == 200
    tick = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "persistent-encounter",
            "X-Demo-Admin-Token": "test-admin",
        },
    ).json()["tick"]
    first = client.get(f"/api/v1/world/ticks/{tick['id']}/encounter")
    assert first.status_code == 200

    restarted, _ = persistent_client(database_path)
    persisted = restarted.get(f"/api/v1/encounters/{first.json()['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["event_id"] == first.json()["event_id"]
    assert "relationship_after" not in persisted.json()
    relationship = client.get(
        f"/api/v1/relationships/{persisted.json()['relationship_id']}"
    )
    assert relationship.status_code == 200
    assert relationship.json()["status"] == "active"
