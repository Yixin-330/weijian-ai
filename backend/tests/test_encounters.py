from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.experience import DEMO_RELATIONSHIP_ID, DEMO_USER_ID, ExperienceModule
from app.domain.island_catalog import FixtureIslandCatalog
from app.main import create_app


def make_client() -> tuple[TestClient, ExperienceModule]:
    module = ExperienceModule()
    app = create_app(
        settings=Settings(environment="test", demo_admin_token="test-admin"),
        experience=module,
        island_catalog=FixtureIslandCatalog(),
    )
    return TestClient(app), module


def run_demo_tick(client: TestClient, key: str = "encounter-demo") -> dict:
    response = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": key,
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert response.status_code == 202
    return response.json()["tick"]


def test_tick_creates_bounded_fixture_encounter_and_advances_relationship():
    client, module = make_client()
    client.post("/api/v1/demo/bootstrap")
    tick = run_demo_tick(client)

    response = client.get(f"/api/v1/world/ticks/{tick['id']}/encounter")
    assert response.status_code == 200
    encounter = response.json()
    assert encounter["fixture_version"] == "v2"
    assert encounter["event_id"] == "stability-light-allocation"
    assert encounter["status"] == "completed"
    assert 2 <= len(encounter["turns"]) <= 5
    assert encounter["return_question"].endswith("？")
    assert encounter["source_mode"] == "fixture"
    assert encounter["relationship_before"] == "shared_experience"
    assert encounter["relationship_after"] == "cared"

    direct = client.get(f"/api/v1/encounters/{encounter['id']}")
    assert direct.status_code == 200
    assert direct.json() == encounter
    relationship = client.get(
        f"/api/v1/relationships/{DEMO_RELATIONSHIP_ID}"
    ).json()
    assert relationship["stage"] == "cared"
    assert relationship["source_mode"] == "live"
    assert encounter["shared_memory"] in relationship["shared_experiences"]
    assert module.audit_count >= 2


def test_tick_retry_reuses_the_same_encounter():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    first_tick = run_demo_tick(client, "same-encounter")
    first = client.get(
        f"/api/v1/world/ticks/{first_tick['id']}/encounter"
    ).json()
    second_tick = run_demo_tick(client, "same-encounter")
    second = client.get(
        f"/api/v1/world/ticks/{second_tick['id']}/encounter"
    ).json()
    assert second_tick["id"] == first_tick["id"]
    assert second["id"] == first["id"]


def test_single_lifeform_tick_completes_without_forcing_an_encounter():
    client, _ = make_client()
    created = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "single-lifeform"},
        json={
            "current_question": "稳定与新的可能之间应该怎样选择？",
            "long_term_topics": ["choice_uncertainty"],
            "exploration_style": "observe",
            "social_pace": "open_to_connection",
            "allow_memory_inference": True,
            "allow_social_recommendation": True,
        },
    )
    user_id = created.json()["user"]["id"]
    tick = client.post(
        "/api/v1/world/ticks",
        json={"user_id": user_id, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "single-tick",
            "X-Demo-Admin-Token": "test-admin",
        },
    ).json()["tick"]
    response = client.get(f"/api/v1/world/ticks/{tick['id']}/encounter")
    assert response.status_code == 404
