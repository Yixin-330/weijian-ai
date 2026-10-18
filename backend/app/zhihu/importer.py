"""一次性导入编排。

设计要点（PRD 8.4 / 8.12）：

1. **预算有界**：整次导入调用次数不超过 `import_call_budget`（默认 6）。
   超预算即停止并保留已获数据，不抛异常丢弃成果。
2. **快照优先**：原始响应（剔除敏感字段后）整体落库；
   所有派生推导从快照执行，**重新推导绝不重新调用接口**。
3. **逐项授权**：三类导入默认关闭，用户逐项开启；未开启的一次调用都不发。
4. **不轮询**：只由用户显式触发，没有定时同步。

调用预算分配（顺序即优先级，额度不足时后面的自动放弃）：

    /user/contents          1 次   本人创作（最高权重信号）
    /user/favlists          1 次   收藏夹自命名（第二权重）
    /user/collections       1 次   近期收藏
    /user/favlist_contents  0-2 次 仅取用户选中的收藏夹，各 1 页
    /user/followees         1 次   关注对象（P1）

基础信息接口不占 `user_data` 额度，单独调用。
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

from .config import (
    PATH_COLLECTIONS,
    PATH_CONTENTS,
    PATH_FAVLIST_CONTENTS,
    PATH_FAVLISTS,
    PATH_FOLLOWEES,
    QUOTA_GROUP_USER_DATA,
    ZhihuSettings,
)
from .client import ZhihuClient
from .errors import AuthError, QuotaExhausted, RateLimited, ZhihuError
from .quota import CallBudget, QuotaGate
from .schemas import (
    CollectionContentItem,
    ContentItem,
    FavlistRecord,
    FolloweeItem,
    SignalKind,
    UserProfile,
)

PAGE_LIMIT = 50  # 接口上限，首屏一次取满以节省调用次数
MAX_FAVLIST_DRILLDOWN = 2  # 最多下钻两个收藏夹


@dataclass(frozen=True)
class ImportConsent:
    """逐项导入授权。默认全部关闭（NFR-SEC-001 最小化收集）。"""

    authored_content: bool = False
    favorites: bool = False
    followees: bool = False
    # 用户选中要下钻的收藏夹（出站字符串形式的 UrlToken）
    selected_favlists: tuple[str, ...] = ()

    @property
    def any_enabled(self) -> bool:
        return self.authored_content or self.favorites or self.followees


@dataclass
class RawSnapshot:
    """平台原始响应快照。

    只追加不覆盖：重新导入产生新快照行，旧快照保留以维持历史审计可回溯
    （PRD 8.12 撤销授权不影响历史审计）。
    """

    api: str
    path: str
    params: dict[str, Any]
    items: list[dict]
    fetched_at: float = field(default_factory=time.time)


@dataclass
class EvidenceSignal:
    """从快照派生的单条证据。

    这是记忆层的输入。`kind` 决定权重与是否可承载立场；
    `occurred_on` 用于判定长期记忆晋升所需的「跨 ≥2 个自然日」。

    ## snapshot_index 为什么必填

    `evidence.snapshot_id` 有外键指向 `platform_import_snapshots`，而快照存在
    的全部意义是「派生推导可以从快照重跑」（PRD 8.12 / TC-IMP-003）。信号原本
    只是紧跟在它所属快照之后被追加进 `ImportResult.signals`，配对关系只存在于
    追加顺序里、从不被记录——落库时每条证据的 `snapshot_id` 都只能写 NULL，
    外键与可重跑保证同时失效。

    记的是**下标**而不是 `api`：`user/favlist_contents` 会产生多个 `api` 相同的
    快照，仅凭 `api` 无法判定某条证据出自哪一个收藏夹。

    没有默认值是刻意的：新增信号源时漏填会在构造处立即失败，
    而默认值只会让证据安静地挂到错误的快照上。
    """

    kind: SignalKind
    text: str
    source_url: str
    occurred_at: int
    stance_eligible: bool
    snapshot_index: int

    @property
    def occurred_on(self) -> str:
        """证据所属自然日，用于跨日判定。"""
        if self.occurred_at <= 0:
            return ""
        return dt.datetime.fromtimestamp(
            self.occurred_at, dt.timezone.utc
        ).strftime("%Y-%m-%d")


@dataclass
class ImportResult:
    """一次导入的完整结果与审计信息。"""

    profile: UserProfile | None = None
    snapshots: list[RawSnapshot] = field(default_factory=list)
    signals: list[EvidenceSignal] = field(default_factory=list)
    calls_spent: int = 0
    calls_planned: tuple[str, ...] = ()
    budget_exhausted: bool = False
    partial_reason: str | None = None

    def add_snapshot(self, snapshot: RawSnapshot) -> int:
        """登记一份快照并返回其下标，供随后派生的证据引用。

        追加与取下标写在一处：调用方拿不到「还没入列的下标」，
        也无法把证据挂到上一份快照上。
        """
        self.snapshots.append(snapshot)
        return len(self.snapshots) - 1

    @property
    def signal_kinds(self) -> set[SignalKind]:
        return {s.kind for s in self.signals}

    @property
    def distinct_days(self) -> set[str]:
        return {s.occurred_on for s in self.signals if s.occurred_on}

    @property
    def has_authored_evidence(self) -> bool:
        """是否包含用户自撰证据——长期记忆晋升的必要条件之一。"""
        return any(s.stance_eligible for s in self.signals)


class ZhihuImporter:
    """按预算执行一次性导入。"""

    def __init__(
        self,
        client: ZhihuClient,
        gate: QuotaGate,
        settings: ZhihuSettings,
    ) -> None:
        self._client = client
        self._gate = gate
        self._settings = settings

    async def run(
        self,
        *,
        oauth_token: str,
        consent: ImportConsent,
    ) -> ImportResult:
        """执行导入。

        额度不足时在**任何**业务调用前抛 `QuotaExhausted`；
        预算耗尽时停止并返回已获数据。
        """
        result = ImportResult()

        # 基础信息不占 user_data 额度，先取，用于建立应用内身份。
        result.profile = await self._client.get_user_profile(oauth_token)

        if not consent.any_enabled:
            result.partial_reason = "用户未开启任何导入项"
            return result

        # 额度闸门：预检失败直接拒绝，不留半份快照。
        quota_items = await self._client.get_quota([QUOTA_GROUP_USER_DATA])
        self._gate.preflight(quota_items, api_group=QUOTA_GROUP_USER_DATA)

        budget = self._gate.new_budget()

        try:
            if consent.authored_content:
                await self._fetch_contents(oauth_token, budget, result)
            if consent.favorites:
                await self._fetch_favlists(oauth_token, budget, result)
                await self._fetch_collections(oauth_token, budget, result)
                await self._fetch_favlist_contents(
                    oauth_token, budget, result, consent.selected_favlists
                )
            if consent.followees:
                await self._fetch_followees(oauth_token, budget, result)
        except (RateLimited, QuotaExhausted) as exc:
            # 命中服务端限制后立即停止，不重试，保留已获数据。
            result.partial_reason = f"平台额度或频率受限，已保留部分数据: {exc}"
        except AuthError:
            # 鉴权失败必须向上传播：不能降级为部分成功，
            # 更不能去掉 X-OAuth-Token 重试。
            raise
        except ZhihuError as exc:
            result.partial_reason = f"导入中断，已保留部分数据: {exc}"

        result.calls_spent = budget.spent
        result.calls_planned = budget.calls
        result.budget_exhausted = not budget.can_spend()
        self._gate.ledger.record(QUOTA_GROUP_USER_DATA, budget.spent)
        return result

    # ---- 各信号源 ----

    async def _spend(
        self,
        budget: CallBudget,
        result: ImportResult,
        api: str,
    ) -> bool:
        """预算判定。返回 False 表示应放弃该调用。"""
        if not budget.can_spend():
            result.budget_exhausted = True
            if result.partial_reason is None:
                result.partial_reason = (
                    f"已达单次导入调用预算 {budget.limit} 次，"
                    f"{api} 及后续项目本次未导入"
                )
            return False
        budget.spend(api)
        return True

    async def _fetch_contents(
        self, token: str, budget: CallBudget, result: ImportResult
    ) -> None:
        api = "user/contents"
        if not await self._spend(budget, result, api):
            return
        params = {
            "ContentType": "all",
            "Limit": PAGE_LIMIT,
            "SortField": "ts",
            "SortOrder": "desc",
        }
        items, _paging = await self._client.list_page(
            PATH_CONTENTS, api=api, oauth_token=token, params=params
        )
        index = result.add_snapshot(
            RawSnapshot(api=api, path=PATH_CONTENTS, params=params, items=items)
        )
        # 只取首屏，不翻页：翻页会线性消耗租户级日额度。
        for raw in items:
            item = ContentItem.parse(raw, api=api)
            if not item.evidence_text:
                continue
            result.signals.append(
                EvidenceSignal(
                    kind=SignalKind.AUTHORED_CONTENT,
                    text=item.evidence_text,
                    source_url=item.url,
                    occurred_at=item.created_at,
                    stance_eligible=True,
                    snapshot_index=index,
                )
            )

    async def _fetch_favlists(
        self, token: str, budget: CallBudget, result: ImportResult
    ) -> None:
        api = "user/favlists"
        if not await self._spend(budget, result, api):
            return
        params = {"Limit": PAGE_LIMIT}
        # 该接口没有 Paging，服务端忽略 Offset，不承诺遍历全部收藏夹。
        items, _ = await self._client.list_page(
            PATH_FAVLISTS, api=api, oauth_token=token, params=params, paged=False
        )
        index = result.add_snapshot(
            RawSnapshot(api=api, path=PATH_FAVLISTS, params=params, items=items)
        )
        for raw in items:
            fav = FavlistRecord.parse(raw, api=api)
            if not fav.evidence_text:
                continue
            result.signals.append(
                EvidenceSignal(
                    kind=SignalKind.FAVLIST_NAMING,
                    text=fav.evidence_text,
                    source_url=f"favlist:{fav.wire_token}",
                    # 收藏夹无创建时间，用导入时刻，跨日判定上按当天计。
                    occurred_at=int(time.time()),
                    stance_eligible=False,
                    snapshot_index=index,
                )
            )

    async def _fetch_collections(
        self, token: str, budget: CallBudget, result: ImportResult
    ) -> None:
        api = "user/collections"
        if not await self._spend(budget, result, api):
            return
        params = {"Limit": PAGE_LIMIT}
        # 近期收藏没有 Offset/Paging，不等于完整收藏历史。
        items, _ = await self._client.list_page(
            PATH_COLLECTIONS, api=api, oauth_token=token, params=params, paged=False
        )
        index = result.add_snapshot(
            RawSnapshot(api=api, path=PATH_COLLECTIONS, params=params, items=items)
        )
        self._collect_favorite_items(items, api, result, index)

    async def _fetch_favlist_contents(
        self,
        token: str,
        budget: CallBudget,
        result: ImportResult,
        selected: tuple[str, ...],
    ) -> None:
        api = "user/favlist_contents"
        for wire_token in selected[:MAX_FAVLIST_DRILLDOWN]:
            if not await self._spend(budget, result, api):
                return
            # UrlToken 是 int64；以字符串入站，转回 int 提交。
            try:
                token_int = int(wire_token)
            except ValueError:
                continue
            params = {"FavlistUrlToken": token_int, "Offset": 0, "Limit": PAGE_LIMIT}
            items, _paging = await self._client.list_page(
                PATH_FAVLIST_CONTENTS, api=api, oauth_token=token, params=params
            )
            index = result.add_snapshot(
                RawSnapshot(api=api, path=PATH_FAVLIST_CONTENTS, params=params, items=items)
            )
            self._collect_favorite_items(items, api, result, index)

    def _collect_favorite_items(
        self,
        items: list[dict],
        api: str,
        result: ImportResult,
        snapshot_index: int,
    ) -> None:
        """收藏条目派生。

        `snapshot_index` 必须由调用方传入：本方法服务于 `user/collections` 与
        每一个下钻的 `user/favlist_contents`，自行推算下标会把后者的证据
        全部挂到最后一份快照上。
        """
        for raw in items:
            item = CollectionContentItem.parse(raw, api=api)
            if not item.evidence_text:
                continue
            result.signals.append(
                EvidenceSignal(
                    kind=SignalKind.FAVORITE_ITEM,
                    text=item.evidence_text,
                    source_url=item.url,
                    # 用收藏时间而非内容创建时间：前者才代表用户的行为时刻。
                    occurred_at=item.fav_time or item.created_at,
                    stance_eligible=False,
                    snapshot_index=snapshot_index,
                )
            )

    async def _fetch_followees(
        self, token: str, budget: CallBudget, result: ImportResult
    ) -> None:
        api = "user/followees"
        if not await self._spend(budget, result, api):
            return
        params = {"Offset": 0, "Limit": PAGE_LIMIT}
        items, _paging = await self._client.list_page(
            PATH_FOLLOWEES, api=api, oauth_token=token, params=params
        )
        index = result.add_snapshot(
            RawSnapshot(api=api, path=PATH_FOLLOWEES, params=params, items=items)
        )
        for raw in items:
            followee = FolloweeItem.parse(raw, api=api)
            if not followee.evidence_text:
                continue
            result.signals.append(
                EvidenceSignal(
                    kind=SignalKind.FOLLOWEE_HEADLINE,
                    text=followee.evidence_text,
                    source_url=f"user:{followee.url_token}",
                    occurred_at=int(time.time()),
                    stance_eligible=False,
                    snapshot_index=index,
                )
            )


def rederive(snapshots: list[RawSnapshot]) -> list[EvidenceSignal]:
    """从已有快照重新派生证据，**不发生任何网络调用**。

    这是 TC-IMP-003 的实现依据：调整权重或晋升规则后可以重跑历史数据，
    而不消耗租户级日额度。
    """
    signals: list[EvidenceSignal] = []
    for snapshot_index, snap in enumerate(snapshots):
        if snap.api == "user/contents":
            for raw in snap.items:
                item = ContentItem.parse(raw, api=snap.api)
                if item.evidence_text:
                    signals.append(
                        EvidenceSignal(
                            kind=SignalKind.AUTHORED_CONTENT,
                            text=item.evidence_text,
                            source_url=item.url,
                            occurred_at=item.created_at,
                            stance_eligible=True,
                            snapshot_index=snapshot_index,
                        )
                    )
        elif snap.api == "user/favlists":
            for raw in snap.items:
                fav = FavlistRecord.parse(raw, api=snap.api)
                if fav.evidence_text:
                    signals.append(
                        EvidenceSignal(
                            kind=SignalKind.FAVLIST_NAMING,
                            text=fav.evidence_text,
                            source_url=f"favlist:{fav.wire_token}",
                            occurred_at=int(snap.fetched_at),
                            stance_eligible=False,
                            snapshot_index=snapshot_index,
                        )
                    )
        elif snap.api in ("user/collections", "user/favlist_contents"):
            for raw in snap.items:
                item = CollectionContentItem.parse(raw, api=snap.api)
                if item.evidence_text:
                    signals.append(
                        EvidenceSignal(
                            kind=SignalKind.FAVORITE_ITEM,
                            text=item.evidence_text,
                            source_url=item.url,
                            occurred_at=item.fav_time or item.created_at,
                            stance_eligible=False,
                            snapshot_index=snapshot_index,
                        )
                    )
        elif snap.api == "user/followees":
            for raw in snap.items:
                followee = FolloweeItem.parse(raw, api=snap.api)
                if followee.evidence_text:
                    signals.append(
                        EvidenceSignal(
                            kind=SignalKind.FOLLOWEE_HEADLINE,
                            text=followee.evidence_text,
                            source_url=f"user:{followee.url_token}",
                            occurred_at=int(snap.fetched_at),
                            stance_eligible=False,
                            snapshot_index=snapshot_index,
                        )
                    )
    return signals
