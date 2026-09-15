"""平台响应的类型化契约。

字段名与大小写严格照抄服务端 JSON（`ContentType`、`UrlToken`、`FavTime` 等），
不做驼峰转换，避免与文档对照时产生歧义。

敏感字段在入站边界即丢弃，见 SENSITIVE_FIELDS。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.evidence_policy import is_stance_eligible as _domain_stance_eligible

from .errors import ProtocolError
from .jsonx import to_wire_id

# 默认最小化收集（NFR-SEC-001）：这些字段即使平台返回也不落库。
# gender 是敏感属性且 PRD 禁止其进入匹配特征，从数据流层面直接排除，
# 而不是留到打分阶段依赖跳过逻辑。email / phone_no 与产品功能无关。
SENSITIVE_FIELDS = frozenset({"gender", "Gender", "email", "phone_no", "phone"})


def drop_sensitive(payload: dict) -> dict:
    """递归剔除敏感字段。快照与派生数据都只保存剔除后的版本。"""
    clean: dict = {}
    for key, value in payload.items():
        if key in SENSITIVE_FIELDS:
            continue
        if isinstance(value, dict):
            clean[key] = drop_sensitive(value)
        elif isinstance(value, list):
            clean[key] = [drop_sensitive(v) if isinstance(v, dict) else v for v in value]
        else:
            clean[key] = value
    return clean


class SignalKind(StrEnum):
    """成长养料的信号类型，对应 PRD 8.4 的证据权重阶梯。"""

    AUTHORED_CONTENT = "authored_content"  # 本人创作标题与摘要
    FAVLIST_NAMING = "favlist_naming"  # 收藏夹自命名与描述
    FAVORITE_ITEM = "favorite_item"  # 收藏条目
    FOLLOWEE_HEADLINE = "followee_headline"  # 关注对象一句话介绍


# PRD 8.4 权重阶梯（数值越大权重越高）。应用内信号由记忆层另行定义。
SIGNAL_WEIGHT: dict[SignalKind, int] = {
    SignalKind.AUTHORED_CONTENT: 100,
    SignalKind.FAVLIST_NAMING: 80,
    SignalKind.FAVORITE_ITEM: 40,
    SignalKind.FOLLOWEE_HEADLINE: 20,
}

# 立场（stance）来源白名单。
#
# 白名单本身定义在 `app.domain.evidence_policy`，本模块只做委托：
# 领域层的白名单还包含应用内主动输入与理解校准，那两类信号本适配层
# 见不到。若在此另存一份，两份白名单必然漂移——而漂移的白名单等于没有
# 白名单：拼错或遗漏的来源既不在名单内，也不会被发现。
#
# 依赖方向为适配层 → 领域层，领域层不反向依赖本模块。
STANCE_ELIGIBLE: frozenset[SignalKind] = frozenset(
    kind for kind in SignalKind if _domain_stance_eligible(kind.value)
)


def is_stance_eligible(kind: SignalKind | str) -> bool:
    """该平台信号能否用于形成立场。

    收藏与关注只能说明用户在关注什么，不能说明其立场——收藏一篇内容
    完全可能是为了反驳它。
    """
    value = kind.value if isinstance(kind, SignalKind) else kind
    return _domain_stance_eligible(value)


@dataclass(frozen=True)
class Paging:
    is_end: bool
    next_offset: int | None
    totals: int | None

    @classmethod
    def parse(cls, raw: object, *, api: str) -> "Paging":
        from .jsonx import parse_next_offset

        if not isinstance(raw, dict):
            raise ProtocolError("Paging 结构非对象", api=api)
        is_end = raw.get("IsEnd")
        if not isinstance(is_end, bool):
            raise ProtocolError(f"Paging.IsEnd 类型非法: {is_end!r}", api=api)
        totals = raw.get("Totals")
        return cls(
            is_end=is_end,
            next_offset=parse_next_offset(raw.get("NextOffset"), api=api),
            totals=totals if isinstance(totals, int) else None,
        )

    def next_or_stop(self, *, api: str) -> int | None:
        """返回下一页 Offset；不可继续时返回 None。

        `IsEnd=false` 但缺少 `NextOffset` 属于分页信息不完整，
        必须停止翻页并报错，不能按条数自行推算。
        """
        if self.is_end:
            return None
        if self.next_offset is None:
            raise ProtocolError(
                "IsEnd=false 但缺少 NextOffset，分页信息不完整，已停止翻页", api=api
            )
        return self.next_offset


@dataclass(frozen=True)
class ContentItem:
    """本人创作列表项。只有标题与摘要，**没有全文**。

    注意 LikeCount / CommentCount / FavoriteCount 是**他人对该内容**的互动数，
    不是用户自己点出去的赞，不可用作用户兴趣证据（PRD 8.4）。
    """

    content_type: str
    url: str
    created_at: int
    title: str
    summary: str

    signal_kind = SignalKind.AUTHORED_CONTENT

    @classmethod
    def parse(cls, raw: dict, *, api: str) -> "ContentItem":
        return cls(
            content_type=str(raw.get("ContentType") or ""),
            url=str(raw.get("Url") or ""),
            created_at=int(raw.get("CreatedAt") or 0),
            title=str(raw.get("Title") or ""),
            summary=str(raw.get("Summary") or ""),
        )

    @property
    def evidence_text(self) -> str:
        return f"{self.title}\n{self.summary}".strip()


@dataclass(frozen=True)
class FavlistRecord:
    """收藏夹。`UrlToken` 是 int64，出站必须转字符串。

    用户亲手命名的收藏夹标题与描述是导入数据中唯一兼具主题性与自述性的
    信号，权重高于收藏条目本身。
    """

    url_token: int
    title: str
    description: str
    is_public: bool

    signal_kind = SignalKind.FAVLIST_NAMING

    @classmethod
    def parse(cls, raw: dict, *, api: str) -> "FavlistRecord":
        token = raw.get("UrlToken")
        if isinstance(token, float):
            raise ProtocolError(
                f"收藏夹 UrlToken 为浮点数，可能已丢失精度: {token!r}", api=api
            )
        if not isinstance(token, int) or isinstance(token, bool):
            raise ProtocolError(f"收藏夹 UrlToken 类型非法: {token!r}", api=api)
        return cls(
            url_token=token,
            title=str(raw.get("Title") or ""),
            description=str(raw.get("Description") or ""),
            is_public=bool(raw.get("IsPublic")),
        )

    @property
    def wire_token(self) -> str:
        return to_wire_id(self.url_token)  # type: ignore[return-value]

    @property
    def evidence_text(self) -> str:
        return f"{self.title}\n{self.description}".strip()


@dataclass(frozen=True)
class CollectionContentItem:
    """收藏条目。`FavTime` 为收藏时间，是判断「跨自然日」的依据。"""

    content_type: str
    url: str
    created_at: int
    fav_time: int
    title: str
    summary: str

    signal_kind = SignalKind.FAVORITE_ITEM

    @classmethod
    def parse(cls, raw: dict, *, api: str) -> "CollectionContentItem":
        return cls(
            content_type=str(raw.get("ContentType") or ""),
            url=str(raw.get("Url") or ""),
            created_at=int(raw.get("CreatedAt") or 0),
            fav_time=int(raw.get("FavTime") or 0),
            title=str(raw.get("Title") or ""),
            summary=str(raw.get("Summary") or ""),
        )

    @property
    def evidence_text(self) -> str:
        return f"{self.title}\n{self.summary}".strip()


@dataclass(frozen=True)
class FolloweeItem:
    """关注对象。只取 Headline 作为领域兴趣线索；Gender 已在入站丢弃。"""

    fullname: str
    url_token: str
    headline: str

    signal_kind = SignalKind.FOLLOWEE_HEADLINE

    @classmethod
    def parse(cls, raw: dict, *, api: str) -> "FolloweeItem":
        return cls(
            fullname=str(raw.get("Fullname") or ""),
            url_token=str(raw.get("UrlToken") or ""),
            headline=str(raw.get("Headline") or ""),
        )

    @property
    def evidence_text(self) -> str:
        return self.headline.strip()


@dataclass(frozen=True)
class UserProfile:
    """授权用户基础信息。`uid` 是 int64，全链路以字符串传递。"""

    uid: str
    hash_id: str
    fullname: str
    headline: str
    description: str
    avatar_path: str

    @classmethod
    def parse(cls, raw: dict, *, api: str) -> "UserProfile":
        uid = raw.get("uid")
        if isinstance(uid, float):
            raise ProtocolError(f"uid 为浮点数，可能已丢失精度: {uid!r}", api=api)
        if uid is None or isinstance(uid, bool):
            raise ProtocolError(f"uid 缺失或类型非法: {uid!r}", api=api)
        return cls(
            uid=str(uid),
            hash_id=str(raw.get("hash_id") or ""),
            fullname=str(raw.get("fullname") or ""),
            headline=str(raw.get("headline") or ""),
            description=str(raw.get("description") or ""),
            avatar_path=str(raw.get("avatar_path") or ""),
        )
