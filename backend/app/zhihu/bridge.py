"""平台信号 → 领域证据的翻译层。

## 为什么需要单独一层

`app.domain.promotion` 的模块文档规定：领域层不认识平台信号类型，只认
`EvidenceSource` 词表。而 `app.zhihu.importer` 产出的是 `EvidenceSignal`，
带着 `SignalKind`。两边都不该认识对方——领域层不能 import `app.zhihu`
（否则纯函数层被拖进 httpx 依赖），适配层也不该自己做晋升判定
（`importer.py` 的文档写着「不做记忆判断」）。

翻译发生在这里，依赖方向是适配层 → 领域层，单向。新增 `SignalKind`
时只需在此确认它对应哪个 `EvidenceSource`，晋升规则不受影响。

## 为什么不是直接改字段名

`SignalKind` 四个取值目前与 `EvidenceSource` 的 A 类四项字面相同，所以
翻译看起来只是换个类型。这不是巧合而是刻意对齐，但**必须保持是一次显式
转换**：`coerce_source` 会让拼错或未登记的取值在翻译时就失败，而不是
安静地生成一条来源陌生、永远不在任何白名单内的证据。下方的导入时断言
把「字面相同」这个前提也变成硬约束。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.evidence_policy import EvidenceSource, coerce_source
from app.domain.models import EvidenceIngestRequest
from app.domain.promotion import ImportedSignal

from .importer import EvidenceSignal
from .schemas import SignalKind

# `SignalKind` → `EvidenceSource` 的显式映射。
#
# 写成显式字典而不是 `EvidenceSource(kind.value)`：平台侧枚举将来可能出现
# 领域侧没有对应项的取值（例如新增一种平台行为），那时这里应当报错并要求
# 先在领域词表登记，而不是让 StrEnum 的字面巧合决定语义。
SIGNAL_SOURCE: dict[SignalKind, EvidenceSource] = {
    SignalKind.AUTHORED_CONTENT: EvidenceSource.AUTHORED_CONTENT,
    SignalKind.FAVLIST_NAMING: EvidenceSource.FAVLIST_NAMING,
    SignalKind.FAVORITE_ITEM: EvidenceSource.FAVORITE_ITEM,
    SignalKind.FOLLOWEE_HEADLINE: EvidenceSource.FOLLOWEE_HEADLINE,
}

# 新增 SignalKind 却忘记登记映射时，`translate` 会在运行中抛 KeyError——
# 那是一次导入执行到一半才暴露的错误。宁可在导入模块时就失败。
_UNMAPPED = tuple(sorted(k.value for k in SignalKind if k not in SIGNAL_SOURCE))
if _UNMAPPED:  # pragma: no cover - 配置错误在导入时即暴露
    raise RuntimeError(
        f"SIGNAL_SOURCE 缺少平台信号 {', '.join(_UNMAPPED)}；"
        "新增 SignalKind 时必须同时登记它对应的 EvidenceSource。"
    )


def translate(signal: EvidenceSignal) -> ImportedSignal:
    """把一条平台信号翻译成领域证据。

    `source_url` → `source_ref`：领域层不关心它是不是 URL，收藏夹与关注对象
    的引用形如 `favlist:123` / `user:abc`，不是可点击链接。
    """
    return ImportedSignal(
        source=coerce_source(SIGNAL_SOURCE[signal.kind]),
        text=signal.text,
        source_ref=signal.source_url,
        occurred_at=signal.occurred_at,
    )


def translate_all(signals: list[EvidenceSignal]) -> tuple[ImportedSignal, ...]:
    """批量翻译。保持原顺序，便于对照快照排查。"""
    return tuple(translate(s) for s in signals)


def to_ingest_request(
    signal: EvidenceSignal,
    *,
    snapshot_id: str,
    import_job_id: str,
    ordinal: int,
    allow_social_recommendation: bool,
) -> EvidenceIngestRequest:
    """Translate one platform signal into the canonical evidence-ingest DTO.

    Topic classification happens after ingestion. Keeping the initial topic as
    ``unclassified`` retains unknown text without inventing an explanation.
    """

    occurred_at = (
        datetime.fromtimestamp(signal.occurred_at, timezone.utc)
        if signal.occurred_at > 0
        else None
    )
    source = coerce_source(SIGNAL_SOURCE[signal.kind])
    return EvidenceIngestRequest(
        ingestion_key=f"zhihu:{import_job_id}:{signal.snapshot_index}:{ordinal}",
        source=source,
        content_text=signal.text,
        source_ref=signal.source_url,
        topic_code="unclassified",
        self_reference=source
        in {EvidenceSource.AUTHORED_CONTENT, EvidenceSource.FAVLIST_NAMING},
        assertion_mode="platform_import",
        confidence=0.6 if signal.stance_eligible else 0.4,
        allow_social_recommendation=allow_social_recommendation,
        snapshot_id=snapshot_id,
        source_occurred_at=occurred_at,
    )
