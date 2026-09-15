from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.experience import (
    DEMO_LIFEFORM_ID,
    DEMO_MEMORY_ID,
    DEMO_RELATIONSHIP_ID,
    DEMO_USER_ID,
    ExperienceModule,
)
from app.domain.island_policy import ISLAND_INTIMACY, ISLAND_STABILITY
from app.islands import DEFAULT_VERSION
from app.main import create_app


def make_client() -> tuple[TestClient, ExperienceModule]:
    module = ExperienceModule()
    settings = Settings(environment="test", demo_admin_token="test-admin")
    return TestClient(create_app(settings=settings, experience=module)), module


def test_health_exposes_trace_id_without_echoing_invalid_value():
    client, _ = make_client()
    response = client.get("/health", headers={"X-Trace-Id": "contains spaces"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Trace-Id"] != "contains spaces"


def test_readiness_uses_experience_adapter():
    client, _ = make_client()
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "storage": True,
        "queue": True,
        "islands": True,
    }


def test_island_catalog_exposes_real_questions_and_safe_materials():
    client, _ = make_client()
    response = client.get("/api/v1/islands")
    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_version"] == DEFAULT_VERSION
    assert [island["island_id"] for island in payload["islands"]] == [
        "stability",
        "intimacy",
        "ai_loneliness",
    ]
    for island in payload["islands"]:
        assert island["source"]["question_url"].startswith(
            "https://www.zhihu.com/question/"
        )
        assert island["viewpoint_count"] == len(island["viewpoint_materials"])
        assert island["viewpoint_count"] > 0
        assert all(
            material["source_url"] for material in island["viewpoint_materials"]
        )


def test_demo_bootstrap_is_idempotent_and_precomputed():
    client, _ = make_client()
    first = client.post("/api/v1/demo/bootstrap")
    second = client.post("/api/v1/demo/bootstrap")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["source_mode"] == "precomputed"
    assert first.json()["lifeform"]["id"] == DEMO_LIFEFORM_ID
    assert first.json()["relationships"][0]["source_mode"] == "precomputed"
    # 演示种子的起始岛同样来自 fixture，与 tick 决策共用一套 ID
    assert first.json()["lifeform"]["current_island_id"] == ISLAND_STABILITY
    assert first.json()["relationships"][0]["island_id"] == ISLAND_STABILITY


def test_four_answer_onboarding_creates_a_live_initial_lifeform():
    client, module = make_client()
    response = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "new-user-ai"},
        json={
            "current_question": "AI 陪伴会让真实关系变得更近还是更远？",
            "long_term_topics": ["ai_and_loneliness", "intimacy_and_autonomy"],
            "exploration_style": "inquire",
            "social_pace": "shared_experiences",
            "allow_memory_inference": True,
            "allow_social_recommendation": False,
        },
    )

    assert response.status_code == 201
    world = response.json()
    assert world["source_mode"] == "live"
    assert world["lifeform"]["current_island_id"] == "ai_loneliness"
    assert world["lifeform"]["exploration_tendency"] == "温和追问"
    assert world["lifeform"]["appearance"] == "晨光"
    assert world["relationships"] == []
    assert len(world["memories"]) == 3
    candidate = next(item for item in world["memories"] if item["status"] == "candidate")
    assert candidate["kind"] == "topic"
    assert candidate["confidence"] == 0.82
    assert candidate["allow_social_recommendation"] is False
    assert "AI 陪伴" in candidate["statement"]
    assert module.audit_count == 1


def test_onboarding_retry_is_idempotent():
    client, module = make_client()
    payload = {
        "current_question": "我要继续稳定工作，还是尝试一次新的方向？",
        "long_term_topics": ["choice_uncertainty"],
        "exploration_style": "observe",
        "social_pace": "observe_first",
        "allow_memory_inference": True,
        "allow_social_recommendation": False,
    }
    first = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "same-onboarding"},
        json=payload,
    )
    audit_count = module.audit_count
    second = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "same-onboarding"},
        json=payload,
    )

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert module.audit_count == audit_count


def test_onboarding_requires_explicit_memory_consent():
    client, _ = make_client()
    response = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "no-consent"},
        json={
            "current_question": "最近有什么值得继续探索的问题？",
            "long_term_topics": ["choice_uncertainty"],
            "exploration_style": "act",
            "social_pace": "open_to_connection",
            "allow_memory_inference": False,
            "allow_social_recommendation": False,
        },
    )

    assert response.status_code == 403


def test_candidate_understanding_alias_is_private_and_calibratable():
    client, _ = make_client()
    created = client.post(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": "understanding-alias"},
        json={
            "current_question": "稳定生活和新的挑战之间，我该如何选择？",
            "long_term_topics": ["choice_uncertainty"],
            "exploration_style": "observe",
            "social_pace": "shared_experiences",
            "allow_memory_inference": True,
            "allow_social_recommendation": False,
        },
    ).json()
    user_id = created["user"]["id"]
    lifeform_id = created["lifeform"]["id"]
    candidate = next(
        item for item in created["memories"] if item["status"] == "candidate"
    )

    listed = client.get(
        f"/api/v1/lifeforms/{lifeform_id}/understandings",
        params={"user_id": user_id},
    )
    assert listed.status_code == 200
    assert any(item["id"] == candidate["id"] for item in listed.json()["items"])

    private = client.get(
        f"/api/v1/lifeforms/{lifeform_id}/understandings",
        params={"user_id": "another-user"},
    )
    assert private.status_code == 404

    calibrated = client.post(
        f"/api/v1/understandings/{candidate['id']}/calibrations",
        json={
            "user_id": user_id,
            "decision": "opposes",
            "allow_social_recommendation": False,
        },
    )
    assert calibrated.status_code == 200
    assert calibrated.json()["calibration"] == "opposes"

    tick = client.post(
        f"/api/v1/users/{user_id}/next-action",
        headers={"Idempotency-Key": "understanding-next-action"},
    )
    assert tick.status_code == 202
    assert "回应" in tick.json()["tick"]["decision_reason"]
    world = client.get(f"/api/v1/users/{user_id}/world").json()
    assert world["lifeform"]["status"].startswith("回应")


def test_wrong_candidate_understanding_stops_steering_the_demo_tick():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    rejected = client.post(
        f"/api/v1/understandings/{DEMO_MEMORY_ID}/calibrations",
        json={
            "user_id": DEMO_USER_ID,
            "decision": "wrong",
            "allow_social_recommendation": False,
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    tick = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "wrong-understanding",
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert tick.status_code == 202
    assert tick.json()["tick"]["selected_island_id"] == ISLAND_STABILITY
    assert "停止使用" in tick.json()["tick"]["decision_reason"]


def test_calibration_then_manual_tick_changes_exploration_direction():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    calibration = client.post(
        f"/api/v1/memories/{DEMO_MEMORY_ID}/calibrations",
        json={
            "user_id": DEMO_USER_ID,
            "decision": "opposes",
            "allow_social_recommendation": False,
        },
    )
    assert calibration.status_code == 200
    assert calibration.json()["status"] == "confirmed"
    assert calibration.json()["allow_social_recommendation"] is False

    tick = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={
            "Idempotency-Key": "judge-demo-1",
            "X-Demo-Admin-Token": "test-admin",
        },
    )
    assert tick.status_code == 202
    assert tick.json()["status"] == "completed"
    # 岛屿 ID 来自当前发布的版本化 fixture。
    assert tick.json()["tick"]["selected_island_id"] == ISLAND_INTIMACY
    assert tick.json()["tick"]["source_mode"] == "live"
    # 每次 tick 记录所用的 fixture 版本，便于回溯决策依据
    assert tick.json()["tick"]["fixture_version"] == DEFAULT_VERSION
    # 决策理由须引用真实知乎问题标题，而不是自造文案
    assert "亲密" in tick.json()["tick"]["decision_reason"]

    job = client.get(f"/api/v1/world/tick-jobs/{tick.json()['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert job.json()["tick"]["id"] == tick.json()["tick"]["id"]

    world = client.get(f"/api/v1/users/{DEMO_USER_ID}/world")
    assert world.json()["source_mode"] == "live"
    assert world.json()["lifeform"]["current_island_id"] == ISLAND_INTIMACY


def test_manual_tick_is_idempotent():
    client, module = make_client()
    client.post("/api/v1/demo/bootstrap")
    headers = {
        "Idempotency-Key": "same-tick",
        "X-Demo-Admin-Token": "test-admin",
    }
    first = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers=headers,
    )
    audit_count = module.audit_count
    second = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers=headers,
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["tick"]["id"] == second.json()["tick"]["id"]
    assert module.audit_count == audit_count


def test_manual_tick_requires_admin_token():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    response = client.post(
        "/api/v1/world/ticks",
        json={"user_id": DEMO_USER_ID, "trigger_type": "manual"},
        headers={"Idempotency-Key": "missing-admin-token"},
    )
    assert response.status_code == 422


def test_private_memory_is_not_disclosed_to_another_user():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    response = client.post(
        f"/api/v1/memories/{DEMO_MEMORY_ID}/calibrations",
        json={
            "user_id": "another-user",
            "decision": "like_me",
            "allow_social_recommendation": True,
        },
    )
    assert response.status_code == 404


def test_precomputed_relationship_can_be_read():
    client, _ = make_client()
    client.post("/api/v1/demo/bootstrap")
    response = client.get(f"/api/v1/relationships/{DEMO_RELATIONSHIP_ID}")
    assert response.status_code == 200
    assert response.json()["stage"] == "shared_experience"
    assert response.json()["source_mode"] == "precomputed"
