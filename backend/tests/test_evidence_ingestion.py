from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select

from app.domain.errors import Conflict
from app.domain.evidence_ingestion import build_evidence_record
from app.domain.experience import ExperienceModule
from app.domain.models import EvidenceIngestRequest, OnboardingRequest
from app.storage.mysql import MySqlExperienceModule
from app.storage.schema import evidence, metadata
from app.zhihu.bridge import to_ingest_request
from app.zhihu.importer import EvidenceSignal
from app.zhihu.schemas import SignalKind


def onboarding_request() -> OnboardingRequest:
    return OnboardingRequest(
        current_question="稳定工作和新的方向之间，我该如何选择？",
        long_term_topics=("choice_uncertainty",),
        exploration_style="observe",
        social_pace="shared_experiences",
        allow_memory_inference=True,
        allow_social_recommendation=True,
    )


def test_source_derives_authorship_and_sensitive_evidence_stays_private():
    record = build_evidence_record(
        user_id="user-1",
        consent_version=3,
        request=EvidenceIngestRequest(
            ingestion_key="input:1",
            source="in_app_input",
            content_text="  我正在重新思考亲密关系里的边界。  ",
            topic_code="intimacy_and_autonomy",
            is_sensitive=True,
            allow_social_recommendation=True,
        ),
    )

    assert record.authored_by_user is True
    assert record.content_text == "我正在重新思考亲密关系里的边界。"
    assert record.allow_social_recommendation is False
    assert record.consent_version == 3


def test_platform_and_in_app_sources_cannot_cross_snapshot_boundary():
    with pytest.raises(Conflict, match="platform evidence"):
        build_evidence_record(
            user_id="user-1",
            consent_version=1,
            request=EvidenceIngestRequest(
                ingestion_key="zhihu:missing-snapshot",
                source="favorite_item",
                content_text="一个收藏条目",
            ),
        )

    with pytest.raises(Conflict, match="in-app evidence"):
        build_evidence_record(
            user_id="user-1",
            consent_version=1,
            request=EvidenceIngestRequest(
                ingestion_key="input:bad-snapshot",
                source="in_app_input",
                content_text="一条应用内输入",
                snapshot_id="snapshot-1",
            ),
        )


def test_ingestion_key_is_idempotent_but_cannot_be_reused_for_another_fact():
    module = ExperienceModule()
    world = module.onboard(onboarding_request(), idempotency_key="evidence-user")
    request = EvidenceIngestRequest(
        ingestion_key="returned-question:1",
        source="returned_question_reply",
        content_text="我愿意先听完对方如何定义自由。",
        topic_code="intimacy_and_autonomy",
        self_reference=True,
        allow_social_recommendation=True,
    )

    first = module.ingest_evidence(world.user.id, request)
    second = module.ingest_evidence(world.user.id, request)
    assert second == first

    with pytest.raises(Conflict, match="already used"):
        module.ingest_evidence(
            world.user.id,
            request.model_copy(update={"content_text": "同一个键下的不同事实"}),
        )


def test_mysql_ingestion_persists_content_and_onboarding_uses_same_contract(tmp_path):
    database_path = tmp_path / "m1-evidence.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    metadata.create_all(engine)
    module = MySqlExperienceModule(engine)
    world = module.onboard(onboarding_request(), idempotency_key="mysql-evidence-user")

    created = module.ingest_evidence(
        world.user.id,
        EvidenceIngestRequest(
            ingestion_key="browse:screen:42",
            source="in_app_browse",
            content_text="亲密与自由岛的核心问题",
            source_ref="island:intimacy",
            topic_code="intimacy_and_autonomy",
            confidence=0.2,
        ),
    )
    module.close()

    restarted = MySqlExperienceModule(
        create_engine(f"sqlite+pysqlite:///{database_path}")
    )
    assert restarted.get_evidence(created.id, user_id=world.user.id) == created
    with restarted._engine.connect() as connection:
        rows = connection.execute(
            select(func.count()).select_from(evidence).where(
                evidence.c.user_id == world.user.id
            )
        ).scalar_one()
        assert rows == 3  # current question + selected topic + browse event
        assert connection.execute(
            select(evidence.c.content_text).where(evidence.c.user_id == world.user.id)
        ).scalars().all()
    restarted.close()


def test_zhihu_bridge_produces_canonical_snapshot_bound_request():
    signal = EvidenceSignal(
        kind=SignalKind.AUTHORED_CONTENT,
        text="我如何看待稳定和冒险",
        source_url="https://www.zhihu.com/question/1/answer/2",
        occurred_at=1_700_000_000,
        stance_eligible=True,
        snapshot_index=2,
    )
    request = to_ingest_request(
        signal,
        snapshot_id="snapshot-2",
        import_job_id="job-9",
        ordinal=4,
        allow_social_recommendation=True,
    )

    assert request.ingestion_key == "zhihu:job-9:2:4"
    assert request.snapshot_id == "snapshot-2"
    assert request.topic_code == "unclassified"
    assert request.source_occurred_at == datetime.fromtimestamp(
        signal.occurred_at, timezone.utc
    )
