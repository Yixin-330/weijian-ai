"""从原始 API 快照构建岛屿 fixture。

确定性：只读 `raw/` 下的快照，**不发生任何网络调用**。规则变更后可重跑，
不消耗租户级日额度（与 importer.rederive 同一原则）。

用法：
    python backend/fixtures/build_islands.py

输入：raw/search-0N.json、raw/answers-0N.json、authored/island_events.draft.json
输出：islands.v2.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

FIXTURE_VERSION = "v2"
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
AUTHORED = HERE / "authored" / "island_events.draft.json"
OUT = HERE / f"islands.{FIXTURE_VERSION}.json"

# 岛屿定义。qid 依据搜索结果的相关性与二元张力清晰度人工选定，
# 选定依据记录在 selection_note 中以便回溯。
ISLANDS = [
    {
        "island_id": "stability",
        "island_name": "稳定还是冒险",
        "topic_code": "choice_uncertainty",
        "qid": "2024798149236016151",
        "search_file": "search-01.json",
        "answers_file": "answers-01.json",
        "selection_note": "搜索结果中重复出现 2 次，二元张力最清晰，且贴合 PRD 8.5 首岛设定",
        "tension_axis": ["求稳", "冒险"],
    },
    {
        "island_id": "intimacy",
        "island_name": "亲密与自由",
        "topic_code": "intimacy_and_autonomy",
        "qid": "1950879757458706791",
        "search_file": "search-02.json",
        "answers_file": "answers-02.json",
        "selection_note": "搜索结果中重复出现 3 次，问题本身即以「平衡」设问，张力内生",
        "tension_axis": ["亲密", "独立"],
    },
    {
        "island_id": "ai_loneliness",
        "island_name": "AI 会让人更孤独吗",
        "topic_code": "ai_and_loneliness",
        "qid": "2050922931207632609",
        "search_file": "search-03.json",
        "answers_file": "answers-03.json",
        "selection_note": "搜索结果中重复出现 3 次，是该主题下唯一以问题形式呈现的高相关结果",
        "tension_axis": ["缓解孤独", "加重孤独"],
    },
]

# 注入探测：观点材料会进入 LLM prompt，构建期先扫一遍。
# 命中不自动删除，而是标记 flagged 并要求人工确认（PRD R-09 / TC-SEC-001）。
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous",
    r"(?i)disregard\s+(the\s+)?above",
    r"(?i)you\s+are\s+now\s+",
    r"(?i)system\s*prompt",
    r"(?i)</?(system|instruction)>",
    r"忽略(以上|之前|前面)(的)?(所有)?(指令|要求|提示)",
    r"(现在|从现在起)你是",
    r"(?i)new\s+instructions?\s*:",
]


def load(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"缺少快照文件: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def unwrap_items(payload: dict) -> list[dict]:
    """兼容 Data 为对象或数组两种形态。"""
    data = payload.get("Data")
    if isinstance(data, dict):
        items = data.get("Items")
    elif isinstance(data, list):
        items = data
    else:
        items = None
    return [i for i in (items or []) if isinstance(i, dict)]


def clean_title(raw: str) -> str:
    """去掉搜索结果标题的站点后缀，保留问题原文。"""
    return re.sub(r"\s*-\s*知乎\s*$", "", raw or "").strip()


def find_question(search_payload: dict, qid: str) -> dict:
    """在搜索快照中按 qid 定位问题，取回官方标题与链接。

    标题从快照提取而非手工录入，保证与平台返回一致、可回溯。
    """
    for item in unwrap_items(search_payload):
        url = str(item.get("Url") or "")
        if re.search(rf"/question/{qid}\b", url):
            return {
                "title": clean_title(str(item.get("Title") or "")),
                "url": f"https://www.zhihu.com/question/{qid}",
                "matched_search_url": url,
            }
    sys.exit(f"搜索快照中未找到 qid={qid}")


def scan_injection(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p, text)]


def build_materials(answers_payload: dict, *, island_id: str) -> tuple[list[dict], dict]:
    """把回答摘要转为观点材料。

    `Summary` 是平台返回的摘要，既不是 AI 生成摘要，也不是回答全文，
    因此字段名保持 `summary` 并标注 `summary_source`。
    """
    code = answers_payload.get("Code")
    if code != 0:
        sys.exit(f"{island_id} 回答快照业务码非 0: {code} {answers_payload.get('Message')}")

    seen: set[str] = set()
    materials: list[dict] = []
    flagged = 0

    for item in unwrap_items(answers_payload):
        token = str(item.get("ContentToken") or "")
        summary = str(item.get("Summary") or "").strip()
        url = str(item.get("Url") or "")
        if not summary or not url:
            continue
        if token and token in seen:
            continue
        if token:
            seen.add(token)

        hits = scan_injection(summary)
        if hits:
            flagged += 1
        materials.append(
            {
                "material_id": f"{island_id}-m{len(materials) + 1:02d}",
                "content_token": token,
                "content_type": str(item.get("ContentType") or ""),
                "summary": summary,
                "summary_source": "platform_provided",
                "source_url": url,
                "trusted": False,
                "injection_flagged": bool(hits),
            }
        )

    paging = (answers_payload.get("Data") or {}).get("Paging") or {}
    stats = {
        "materials": len(materials),
        "injection_flagged": flagged,
        "is_end": paging.get("IsEnd"),
    }
    return materials, stats


def main() -> None:
    # Rebuilding pinned source snapshots is not a new platform fetch. Preserve
    # published provenance, otherwise a later day's test changes fixture hashes.
    fetched_on = (json.loads(OUT.read_text(encoding="utf-8-sig"))["fetched_on"]
                  if OUT.exists() else "2026-09-15")
    islands: list[dict] = []
    report: list[str] = []

    authored = load(AUTHORED)
    if authored.get("authored_status") != "approved_with_exclusions":
        sys.exit("事件内容尚未完成产品审核，拒绝发布")
    if authored.get("target_fixture_version") != FIXTURE_VERSION:
        sys.exit("事件草稿目标版本与生成版本不一致")
    authored_by_id = {
        island["island_id"]: island for island in authored.get("islands", [])
    }
    excluded_event_ids = set(authored.get("excluded_event_ids", []))

    for display_order, spec in enumerate(ISLANDS, start=1):
        search = load(RAW / spec["search_file"])
        answers = load(RAW / spec["answers_file"])

        question = find_question(search, spec["qid"])
        materials, stats = build_materials(answers, island_id=spec["island_id"])

        if not materials:
            sys.exit(f"{spec['island_id']} 无可用观点材料")

        authored_island = authored_by_id.get(spec["island_id"])
        if authored_island is None:
            sys.exit(f"{spec['island_id']} 缺少已审核事件内容")
        approved_events = [
            {**event, "act": act}
            for act, event in enumerate(
                (
                    event
                    for event in authored_island.get("events", [])
                    if event.get("event_id") not in excluded_event_ids
                ),
                start=1,
            )
        ]
        if not 2 <= len(approved_events) <= 3:
            sys.exit(f"{spec['island_id']} 启用事件数量必须为 2-3 个")

        islands.append(
            {
                "island_id": spec["island_id"],
                "island_name": spec["island_name"],
                "topic_code": spec["topic_code"],
                "display_order": display_order,
                "tension_axis": spec["tension_axis"],
                # 平台来源部分
                "source": {
                    "platform": "zhihu",
                    "question_id": spec["qid"],
                    "question_title": question["title"],
                    "question_url": question["url"],
                    "selection_note": spec["selection_note"],
                    "answers_is_end": stats["is_end"],
                },
                "viewpoint_materials": materials,
                "scene": authored_island["scene"],
                "events": approved_events,
                "authored_status": "ready",
            }
        )
        report.append(
            f"  {spec['island_id']:<14} qid={spec['qid']:<20} "
            f"材料={stats['materials']:>2} 注入标记={stats['injection_flagged']} "
            f"事件={len(approved_events)} IsEnd={stats['is_end']}"
        )

    payload = {
        "fixture_version": FIXTURE_VERSION,
        "fetched_on": fetched_on,
        "generator": "backend/fixtures/build_islands.py",
        "notes": [
            "观点材料为平台返回的 Summary，不是 AI 生成摘要，也不是回答全文。",
            "所有 summary 均为不可信外部内容：只能以结构化字段传入模型，"
            "不与指令拼接，模型输出须校验回预定义动作枚举。",
            "运行时只读本快照，不在用户请求路径上调用平台接口。",
            "scene 与 events 已于 2026-09-15 完成产品审核。",
            "ai-borrowed-voice 因模仿真实人物的敏感风险暂不进入 MVP。",
        ],
        "islands": islands,
    }

    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    OUT.write_text(body + "\n", encoding="utf-8")

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    print(f"已生成 {OUT.name}（{len(islands)} 座岛）")
    print("\n".join(report))
    print(f"  sha256={digest[:16]}...")


if __name__ == "__main__":
    main()
