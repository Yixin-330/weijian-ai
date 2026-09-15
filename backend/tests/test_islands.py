"""岛屿 fixture 与加载器测试。

验证两类属性：
1. 真实 fixture 符合 PRD 8.5 的议题绑定与来源标注要求；
2. 加载器会拒绝破坏安全契约的 fixture（trusted 标记、缺来源、非知乎链接）。
"""

from __future__ import annotations

import json

import pytest

from app.islands import DEFAULT_VERSION, FixtureError, load_islands

REAL = load_islands()


# ---------- 真实 fixture 契约 ----------


def test_three_islands_present():
    assert REAL.ids == ("stability", "intimacy", "ai_loneliness")
    assert REAL.fixture_version == DEFAULT_VERSION == "v2"
    assert REAL.fetched_on  # 抓取日期必须留痕
    assert [island.display_order for island in REAL.islands] == [1, 2, 3]
    assert len({island.topic_code for island in REAL.islands}) == 3


def test_every_island_bound_to_real_zhihu_question():
    """PRD 8.5：议题必须来自真实知乎问题，不是虚构文本。"""
    for island in REAL.islands:
        src = island.source
        assert src.platform == "zhihu"
        assert src.question_id.isdigit()
        assert src.question_url == f"https://www.zhihu.com/question/{src.question_id}"
        assert src.question_title  # 标题从快照提取，非手工录入
        assert src.selection_note  # 选题依据可回溯


def test_materials_carry_source_links():
    """展示观点材料时必须保留原文链接，不得隐去来源。"""
    for island in REAL.islands:
        assert len(island.viewpoint_materials) >= 10
        for m in island.viewpoint_materials:
            assert m.source_url.startswith("https://")
            assert m.summary.strip()


def test_all_materials_untrusted():
    """外部内容恒为不可信，且不可被构造参数翻转。"""
    for island in REAL.islands:
        for m in island.viewpoint_materials:
            assert m.trusted is False


def test_no_injection_flagged_in_current_fixture():
    for island in REAL.islands:
        assert island.safe_materials() == island.viewpoint_materials


def test_prompt_field_does_not_concatenate_text():
    """交给 Agent 层的是结构化字段，不是拼好的 prompt 文本。"""
    m = REAL.by_id("stability").viewpoint_materials[0]
    field = m.as_prompt_field()
    assert set(field) == {"material_id", "untrusted_summary", "source_url"}
    # 字段名本身携带 untrusted 语义，防止下游误当可信输入
    assert "untrusted" in "".join(field.keys())


def test_tension_axis_is_binary():
    """二元张力用于配对的倒 U 型计分，必须恰好两极。"""
    for island in REAL.islands:
        assert len(island.tension_axis) == 2
        assert island.tension_axis[0] != island.tension_axis[1]


def test_approved_authored_content_is_ready_for_encounters():
    """已审核的场景与事件可以进入双 Agent 相遇。"""
    expected_counts = {"stability": 3, "intimacy": 3, "ai_loneliness": 2}
    for island in REAL.islands:
        assert island.authored_status == "ready"
        assert len(island.events) == expected_counts[island.island_id]
        assert [event["act"] for event in island.events] == list(
            range(1, len(island.events) + 1)
        )
        assert island.design_ready


def test_sensitive_borrowed_voice_event_is_not_published():
    event_ids = {
        event["event_id"] for island in REAL.islands for event in island.events
    }
    assert len(event_ids) == 8
    assert "ai-borrowed-voice" not in event_ids


def test_by_id_rejects_unknown():
    with pytest.raises(FixtureError, match="未知岛屿"):
        REAL.by_id("nope")


def test_no_author_or_sensitive_fields_in_fixture():
    """回答摘要接口不返回作者信息；确认 fixture 里也没有个人数据。"""
    raw = json.loads(
        (__import__("pathlib").Path(__file__).resolve().parent.parent / "fixtures" / f"islands.{DEFAULT_VERSION}.json").read_text(
            encoding="utf-8"
        )
    )
    text = json.dumps(raw, ensure_ascii=False)
    for banned in ("gender", "email", "phone_no", "AuthorToken", "author_name"):
        assert banned not in text


# ---------- 加载器拒绝破坏契约的 fixture ----------


def _write(tmp_path, payload: dict):
    (tmp_path / "islands.bad.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def _minimal_island(**over) -> dict:
    island = {
        "island_id": "x",
        "island_name": "X",
        "topic_code": "x_topic",
        "display_order": 1,
        "tension_axis": ["a", "b"],
        "source": {
            "platform": "zhihu",
            "question_id": "1",
            "question_title": "t",
            "question_url": "https://www.zhihu.com/question/1",
            "selection_note": "n",
            "answers_is_end": True,
        },
        "viewpoint_materials": [
            {
                "material_id": "x-m01",
                "content_token": "tk",
                "content_type": "answer",
                "summary": "s",
                "source_url": "https://www.zhihu.com/answer/1",
                "injection_flagged": False,
            }
        ],
        "scene": None,
        "events": [],
        "authored_status": "pending_design",
    }
    island.update(over)
    return {"fixture_version": "bad", "fetched_on": "2026-01-01", "islands": [island]}


def test_rejects_trusted_material(tmp_path):
    payload = _minimal_island()
    payload["islands"][0]["viewpoint_materials"][0]["trusted"] = True
    with pytest.raises(FixtureError, match="不得标记为 trusted"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_rejects_material_without_source_url(tmp_path):
    payload = _minimal_island()
    del payload["islands"][0]["viewpoint_materials"][0]["source_url"]
    with pytest.raises(FixtureError, match="source_url"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_rejects_non_zhihu_question_url(tmp_path):
    payload = _minimal_island()
    payload["islands"][0]["source"]["question_url"] = "https://example.com/q/1"
    with pytest.raises(FixtureError, match="必须绑定真实知乎问题"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_rejects_non_binary_axis(tmp_path):
    payload = _minimal_island(tension_axis=["only"])
    with pytest.raises(FixtureError, match="二元张力"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_rejects_duplicate_island_ids(tmp_path):
    payload = _minimal_island()
    payload["islands"].append(payload["islands"][0])
    with pytest.raises(FixtureError, match="ID 重复"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_rejects_missing_materials(tmp_path):
    payload = _minimal_island(viewpoint_materials=[])
    with pytest.raises(FixtureError, match="缺少观点材料"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_ready_island_rejects_unapproved_action(tmp_path):
    event = {
        "event_id": "x-event",
        "act": 1,
        "title": "事件",
        "dilemma": "如何选择？",
        "available_actions": ["impersonate"],
        "max_turns": 3,
        "end_conditions": ["both_completed_turn"],
        "material_limit": 1,
        "return_question": "你会怎么选？",
    }
    payload = _minimal_island(
        scene="测试场景",
        events=[event, {**event, "event_id": "x-event-2", "act": 2}],
        authored_status="ready",
    )
    with pytest.raises(FixtureError, match="未授权动作"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_ready_island_requires_two_events(tmp_path):
    event = {
        "event_id": "x-event",
        "act": 1,
        "title": "事件",
        "dilemma": "如何选择？",
        "available_actions": ["observe"],
        "max_turns": 3,
        "end_conditions": ["both_completed_turn"],
        "material_limit": 1,
        "return_question": "你会怎么选？",
    }
    payload = _minimal_island(
        scene="测试场景",
        events=[event],
        authored_status="ready",
    )
    with pytest.raises(FixtureError, match="必须启用 2-3 个事件"):
        load_islands("bad", base_dir=_write(tmp_path, payload))


def test_missing_fixture_raises(tmp_path):
    with pytest.raises(FixtureError, match="缺少 fixture"):
        load_islands("nonexistent", base_dir=tmp_path)


# ---------- 确定性 ----------


def test_build_is_deterministic():
    """重跑构建脚本不应改变输出（同一快照 → 同一 fixture）。"""
    import hashlib
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    target = root / "fixtures" / f"islands.{DEFAULT_VERSION}.json"
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, str(root / "fixtures" / "build_islands.py")],
        check=True,
        capture_output=True,
    )
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
