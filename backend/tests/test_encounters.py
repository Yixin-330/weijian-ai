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


def test_tick_creates_bounded_fixture_encounter_without_inventing_emotional_stage():
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
    assert "relationship_before" not in encounter
    assert "relationship_after" not in encounter

    direct = client.get(f"/api/v1/encounters/{encounter['id']}")
    assert direct.status_code == 200
    assert direct.json() == encounter
    relationship = client.get(
        f"/api/v1/relationships/{DEMO_RELATIONSHIP_ID}"
    ).json()
    assert relationship["status"] == "active"
    assert relationship["encounter_count"] == 2
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


def test_new_lifeform_keeps_its_ai_island_and_meets_a_real_same_island_companion():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    created = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "ai-lifeform-encounter"},
        json={
            "current_question": "AI 陪伴会让真实关系变得更近还是更远？",
            "long_term_topics": ["ai_and_loneliness"],
            "exploration_style": "inquire",
            "social_pace": "open_to_connection",
            "allow_memory_inference": True,
            "allow_social_recommendation": True,
        },
    ).json()

    companion = client.post("/api/v1/onboarding",
        headers={"Idempotency-Key": "ai-real-companion"}, json={
            "current_question": "我想了解AI陪伴与真实关系的差异。",
            "long_term_topics": ["ai_and_loneliness"], "exploration_style": "observe",
            "social_pace": "shared_experiences", "allow_memory_inference": True,
            "allow_social_recommendation": True,
        }).json()

    response = client.post(
        f"/api/v1/users/{created['user']['id']}/next-action",
        headers={"Idempotency-Key": "ai-lifeform-next-action"},
    )
    assert response.status_code == 202
    tick = response.json()["tick"]
    assert tick["selected_island_id"] == "ai_loneliness"

    encounter = client.get(
        f"/api/v1/world/ticks/{tick['id']}/encounter"
    ).json()
    assert encounter["island_id"] == "ai_loneliness"
    assert created["lifeform"]["id"] in encounter["lifeform_ids"]
    assert encounter["event_id"] == "ai-perfect-echo"
    assert companion["lifeform"]["id"] in encounter["lifeform_ids"]
    assert encounter["companion_is_demo"] is False
