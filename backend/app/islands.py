"""岛屿 fixture 加载器。

运行时**只读快照**，不在用户请求路径上调用平台接口（PRD 8.5）。
这既是额度约束的要求，也让固定场景回归结果可复现（PRD 19.2 发布门槛）。

安全边界：观点材料是外部内容，一律 untrusted。本模块只负责把它们作为
结构化字段交出去，绝不拼接成 prompt 文本——拼装由 Agent 层完成，
且必须校验模型输出回预定义动作枚举（PRD R-09 / TC-SEC-001）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
DEFAULT_VERSION = "v2"

ALLOWED_EVENT_ACTIONS = frozenset(
    {"approach", "observe", "respond", "cooperate", "avoid", "leave"}
)
ALLOWED_EVENT_END_CONDITIONS = frozenset(
    {"both_completed_turn", "one_left", "max_turns_reached"}
)


class FixtureError(RuntimeError):
    """fixture 缺失或不符合契约。"""


@dataclass(frozen=True)
class ViewpointMaterial:
    """一条观点材料。

    `summary` 是平台返回的摘要，不是 AI 生成摘要，也不是回答全文；
    展示时必须保留 `source_url`，不得隐去来源。
    """

    material_id: str
    content_token: str
    content_type: str
    summary: str
    source_url: str
    injection_flagged: bool

    # 外部内容恒为不可信。设为类属性而非实例字段，
    # 避免调用方通过构造参数把它翻成 True。
    trusted = False

    def as_prompt_field(self) -> dict[str, str]:
        """交给 Agent 层的结构化表示。

        刻意不返回拼接好的文本：调用方必须把它作为数据字段填入模板，
        而不是把摘要当指令直接串进 prompt。
        """
        return {
            "material_id": self.material_id,
            "untrusted_summary": self.summary,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class IslandSource:
    """岛屿议题的平台来源，用于可解释性与来源标注。"""

    platform: str
    question_id: str
    question_title: str
    question_url: str
    selection_note: str
    answers_is_end: bool | None


@dataclass(frozen=True)
class Island:
    island_id: str
    island_name: str
    topic_code: str
    display_order: int
    tension_axis: tuple[str, str]
    source: IslandSource
    viewpoint_materials: tuple[ViewpointMaterial, ...]
    scene: str | None
    events: tuple[dict, ...]
    authored_status: str

    @property
    def design_ready(self) -> bool:
        """产品自撰内容（场景与事件）是否已就绪。

        PRD 8.5 要求每座岛 2-3 个事件；未就绪的岛不应进入双 Agent 相遇。
        """
        return self.authored_status == "ready" and len(self.events) >= 2

    def safe_materials(self) -> tuple[ViewpointMaterial, ...]:
        """排除注入标记项后的材料。

        标记项保留在 fixture 中以便审计，但默认不进入模型输入。
        """
        return tuple(m for m in self.viewpoint_materials if not m.injection_flagged)


@dataclass(frozen=True)
class IslandSet:
    fixture_version: str
    fetched_on: str
    islands: tuple[Island, ...]

    def by_id(self, island_id: str) -> Island:
        for island in self.islands:
            if island.island_id == island_id:
                return island
        raise FixtureError(f"未知岛屿: {island_id}")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(i.island_id for i in self.islands)


def _parse_material(raw: dict, *, island_id: str) -> ViewpointMaterial:
    summary = str(raw.get("summary") or "").strip()
    source_url = str(raw.get("source_url") or "").strip()
    if not summary:
        raise FixtureError(f"{island_id}: 观点材料缺少 summary")
    if not source_url:
        # 来源链接是可解释性的一部分，缺失即视为契约破坏。
        raise FixtureError(f"{island_id}: 观点材料缺少 source_url")
    if raw.get("trusted") is True:
        raise FixtureError(f"{island_id}: 观点材料不得标记为 trusted")
    return ViewpointMaterial(
        material_id=str(raw.get("material_id") or ""),
        content_token=str(raw.get("content_token") or ""),
        content_type=str(raw.get("content_type") or ""),
        summary=summary,
        source_url=source_url,
        injection_flagged=bool(raw.get("injection_flagged")),
    )


def _parse_event(raw: dict, *, island_id: str) -> dict:
    event_id = str(raw.get("event_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    dilemma = str(raw.get("dilemma") or "").strip()
    return_question = str(raw.get("return_question") or "").strip()
    if not all((event_id, title, dilemma, return_question)):
        raise FixtureError(f"{island_id}: 事件缺少必要文案或 event_id")
    if not return_question.endswith(("？", "?")):
        raise FixtureError(f"{island_id}/{event_id}: return_question 必须是问题")

    act = raw.get("act")
    max_turns = raw.get("max_turns")
    material_limit = raw.get("material_limit")
    if not isinstance(act, int) or act < 1:
        raise FixtureError(f"{island_id}/{event_id}: act 必须为正整数")
    if not isinstance(max_turns, int) or not 2 <= max_turns <= 5:
        raise FixtureError(f"{island_id}/{event_id}: max_turns 必须在 2-5 之间")
    if not isinstance(material_limit, int) or not 1 <= material_limit <= 3:
        raise FixtureError(f"{island_id}/{event_id}: material_limit 必须在 1-3 之间")

    actions = raw.get("available_actions")
    if not isinstance(actions, list) or not actions or len(actions) != len(set(actions)):
        raise FixtureError(f"{island_id}/{event_id}: available_actions 非法")
    if not set(actions) <= ALLOWED_EVENT_ACTIONS:
        raise FixtureError(f"{island_id}/{event_id}: 包含未授权动作")

    conditions = raw.get("end_conditions")
    if (
        not isinstance(conditions, list)
        or not conditions
        or len(conditions) != len(set(conditions))
        or not set(conditions) <= ALLOWED_EVENT_END_CONDITIONS
    ):
        raise FixtureError(f"{island_id}/{event_id}: end_conditions 非法")
    return raw


def _parse_island(raw: dict) -> Island:
    island_id = str(raw.get("island_id") or "")
    if not island_id:
        raise FixtureError("岛屿缺少 island_id")

    topic_code = str(raw.get("topic_code") or "").strip()
    if not topic_code:
        raise FixtureError(f"{island_id}: 缺少 topic_code")
    display_order = raw.get("display_order")
    if not isinstance(display_order, int) or display_order < 1:
        raise FixtureError(f"{island_id}: display_order 必须为正整数")

    axis = raw.get("tension_axis") or []
    if not isinstance(axis, list) or len(axis) != 2:
        raise FixtureError(f"{island_id}: tension_axis 必须为二元张力")

    src = raw.get("source")
    if not isinstance(src, dict):
        raise FixtureError(f"{island_id}: 缺少 source")
    question_url = str(src.get("question_url") or "")
    if "zhihu.com/question/" not in question_url:
        raise FixtureError(f"{island_id}: question_url 非法，议题必须绑定真实知乎问题")

    materials = raw.get("viewpoint_materials") or []
    if not isinstance(materials, list) or not materials:
        raise FixtureError(f"{island_id}: 缺少观点材料")
    if not all(isinstance(material, dict) for material in materials):
        raise FixtureError(f"{island_id}: 观点材料必须全部为对象")

    events = raw.get("events") or []
    if not isinstance(events, list):
        raise FixtureError(f"{island_id}: events 结构非数组")
    if not all(isinstance(event, dict) for event in events):
        raise FixtureError(f"{island_id}: events 必须全部为对象")

    authored_status = str(raw.get("authored_status") or "pending_design")
    scene = str(raw["scene"]).strip() if raw.get("scene") else None
    parsed_events = tuple(_parse_event(event, island_id=island_id) for event in events)
    if authored_status == "ready":
        if not scene:
            raise FixtureError(f"{island_id}: ready 岛屿必须提供 scene")
        if not 2 <= len(parsed_events) <= 3:
            raise FixtureError(f"{island_id}: ready 岛屿必须启用 2-3 个事件")
        if [event["act"] for event in parsed_events] != list(
            range(1, len(parsed_events) + 1)
        ):
            raise FixtureError(f"{island_id}: 事件 act 必须从 1 连续编号")

    return Island(
        island_id=island_id,
        island_name=str(raw.get("island_name") or ""),
        topic_code=topic_code,
        display_order=display_order,
        tension_axis=(str(axis[0]), str(axis[1])),
        source=IslandSource(
            platform=str(src.get("platform") or ""),
            question_id=str(src.get("question_id") or ""),
            question_title=str(src.get("question_title") or ""),
            question_url=question_url,
            selection_note=str(src.get("selection_note") or ""),
            answers_is_end=src.get("answers_is_end")
            if isinstance(src.get("answers_is_end"), bool)
            else None,
        ),
        viewpoint_materials=tuple(_parse_material(m, island_id=island_id) for m in materials),
        scene=scene,
        events=parsed_events,
        authored_status=authored_status,
    )


def load_island_payload(
    version: str = DEFAULT_VERSION,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """读取版本化原始文档，供解析器与持久化发布共用。"""
    directory = base_dir or FIXTURE_DIR
    path = directory / f"islands.{version}.json"
    if not path.exists():
        raise FixtureError(f"缺少 fixture: {path}")

    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise FixtureError("fixture 根节点必须为对象")
    return payload


def parse_islands(payload: dict[str, Any]) -> IslandSet:
    """把文件或数据库中的同一份结构化文档解析为岛屿集合。"""

    islands = payload.get("islands")
    if not isinstance(islands, list) or not islands:
        raise FixtureError("fixture 未包含岛屿")
    if not all(isinstance(island, dict) for island in islands):
        raise FixtureError("islands 必须全部为对象")

    parsed = tuple(sorted((_parse_island(i) for i in islands), key=lambda island: island.display_order))
    ids = [i.island_id for i in parsed]
    if len(set(ids)) != len(ids):
        raise FixtureError(f"岛屿 ID 重复: {ids}")
    orders = [i.display_order for i in parsed]
    if len(set(orders)) != len(orders):
        raise FixtureError(f"岛屿 display_order 重复: {orders}")
    event_ids = [event["event_id"] for island in parsed for event in island.events]
    if len(set(event_ids)) != len(event_ids):
        raise FixtureError("事件 ID 重复")

    return IslandSet(
        fixture_version=str(payload.get("fixture_version") or ""),
        fetched_on=str(payload.get("fetched_on") or ""),
        islands=parsed,
    )


def load_islands(version: str = DEFAULT_VERSION, *, base_dir: Path | None = None) -> IslandSet:
    """加载并校验岛屿 fixture。零网络调用。"""
    return parse_islands(load_island_payload(version, base_dir=base_dir))


@lru_cache(maxsize=4)
def get_islands(version: str = DEFAULT_VERSION) -> IslandSet:
    """进程内缓存的加载入口，供请求路径使用。"""
    return load_islands(version)
