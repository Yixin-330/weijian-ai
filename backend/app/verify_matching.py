"""Explicit development-only MySQL smoke run; preserves its auditable records.

Run with python -m app.verify_matching. No credentials or private evidence are
printed. Test users remain visibly named M2验证用户 in the development database.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

from sqlalchemy import create_engine, update

from app.core.config import Settings
from app.domain.models import OnboardingRequest, TriggerType, EncounterDecisionRequest, ExplorationSettings
from app.storage.mysql import MySqlExperienceModule
from app.storage.schema import users


def main():
    settings = Settings.from_env()
    if settings.environment == "production" or not settings.database_url or not settings.database_url.startswith("mysql"):
        raise RuntimeError("This verification requires a development MySQL database")
    module = MySqlExperienceModule(create_engine(settings.database_url))
    run = uuid4().hex[:12]
    worlds = []
    try:
        for index in range(2):
            world = module.onboard(OnboardingRequest(
                current_question="稳定工作与新的选择之间，我该如何衡量？",
                long_term_topics=("choice_uncertainty",), exploration_style="observe",
                social_pace="shared_experiences", allow_memory_inference=True,
                allow_social_recommendation=True), idempotency_key=f"m2-verify:{run}:{index}")
            worlds.append(world)
            with module._engine.begin() as connection:
                connection.execute(update(users).where(users.c.id == world.user.id)
                    .values(display_name=f"M2验证用户-{run}-{index}"))
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda w: module.run_world_tick(user_id=w.user.id,
                trigger_type=TriggerType.MANUAL, idempotency_key=f"m2-verify:{run}"), worlds))
        seen = set()
        matches = []
        for world, result in zip(worlds, results):
            retry = module.run_world_tick(user_id=world.user.id, trigger_type=TriggerType.MANUAL,
                idempotency_key=f"m2-verify:{run}")
            assert retry.id == result.id
            if result.matching_status != "matched":
                continue
            encounter = module.get_tick_encounter(result.id)
            assert not (seen & set(encounter.lifeform_ids)), "participant reused in concurrent ticks"
            seen.update(encounter.lifeform_ids)
            assert not encounter.companion_is_demo
            snapshot = module.get_context_snapshot(encounter.actor_snapshot_id, user_id=world.user.id)
            assert snapshot.purpose == "social_recommendation"
            decision = module.decide_encounter(encounter.id, EncounterDecisionRequest(
                user_id=world.user.id, decision="end"), idempotency_key=f"m2-verify-end:{run}")
            matches.append(dict(tick_id=result.id, encounter_id=encounter.id,
                actor_snapshot_id=snapshot.id, decision_id=decision["id"]))
        assert matches, "no real encounter completed"
        print(json.dumps({"run": run, "user_ids": [w.user.id for w in worlds],
            "statuses": [r.matching_status for r in results], "matches": matches,
            "verified": ["mysql_persistence", "concurrent_claims", "idempotency", "social_snapshot", "private_decision"]}, indent=2))
    finally:
        for world in worlds:
            module.update_exploration(world.user.id, ExplorationSettings(enabled=False))
        module.close()


if __name__ == "__main__":
    main()
