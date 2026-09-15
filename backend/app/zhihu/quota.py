"""额度闸门。

平台额度按**租户按自然日**计，不是按用户——两个用户 onboarding 就会互相挤占。
因此 PRD 8.4 把它定为架构级约束：导入前必须预检，额度不足时明确拒绝，
而不是让导入跑到一半失败。

`/quota` 查询本身不消耗业务额度，可以安全地在导入前调用。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .config import QUOTA_GROUP_USER_DATA
from .errors import QuotaExhausted


@dataclass(frozen=True)
class QuotaItem:
    """`/api/v1/quota` 返回的单个额度项。"""

    api_id: str
    api_name: str
    total: int
    used: int
    remaining: int


@dataclass
class CallBudget:
    """单次导入的调用预算。

    超预算时停止并保留已获数据（PRD 8.4），因此这里只负责判定，
    由调用方决定如何收尾——不抛异常中断整个导入。
    """

    limit: int
    spent: int = 0
    _log: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def can_spend(self) -> bool:
        return self.spent < self.limit

    def spend(self, api: str) -> None:
        """记一次已发生的调用。调用方须先用 can_spend() 判定。"""
        self.spent += 1
        self._log.append(api)

    @property
    def calls(self) -> tuple[str, ...]:
        return tuple(self._log)


class QuotaLedger:
    """本地调用流水。

    远端额度是租户级的滞后视图；本地流水用于在同一自然日内自我约束，
    并为「这次导入花了几次调用」留下审计记录。

    生产实现应换成 MySQL 表 + Redis 计数器；这里的内存实现只用于
    单进程 Demo 与测试。
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}

    @staticmethod
    def _today() -> str:
        # 平台按自然日重置；此处按 UTC 记账，与服务端口径可能相差时区，
        # 因此本地流水只作为辅助约束，硬判定仍以远端 RemainingQuota 为准。
        return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    def record(self, api_group: str, count: int = 1) -> None:
        key = (self._today(), api_group)
        self._counts[key] = self._counts.get(key, 0) + count

    def used_today(self, api_group: str) -> int:
        return self._counts.get((self._today(), api_group), 0)


class QuotaGate:
    """导入前的额度预检闸门。"""

    def __init__(self, ledger: QuotaLedger, *, budget: int, floor: int) -> None:
        self._ledger = ledger
        self._budget = budget
        self._floor = floor

    def preflight(self, items: list[QuotaItem], *, api_group: str = QUOTA_GROUP_USER_DATA) -> None:
        """确认剩余额度足以覆盖整次导入，否则在**任何**业务调用前拒绝。

        阈值为 预算 + 缓冲：宁可拒绝一次导入，也不要在导入中途耗尽额度
        留下半份快照。
        """
        item = next((i for i in items if i.api_id == api_group), None)
        if item is None:
            # 查不到该额度组时不假设充足，也不静默放行。
            raise QuotaExhausted(
                f"额度查询未返回 {api_group} 额度组，无法确认余量，导入已取消",
                api="quota",
            )

        needed = self._budget + self._floor
        if item.remaining < needed:
            raise QuotaExhausted(
                f"{item.api_name} 今日剩余 {item.remaining} 次，"
                f"低于本次导入所需 {self._budget} 次与安全缓冲 {self._floor} 次，"
                f"导入已取消。请明日再试或改用手动输入。",
                api="quota",
            )

    def new_budget(self) -> CallBudget:
        return CallBudget(limit=self._budget)

    @property
    def ledger(self) -> QuotaLedger:
        return self._ledger
