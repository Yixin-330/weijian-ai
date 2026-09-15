"""知乎开放平台适配层。

边界：本层只负责授权、额度、协议校验与快照落地，**不做记忆判断**。
证据的权重计算、候选理解生成与长期记忆晋升属于记忆层。

分工提醒：官方 CLI 不发起 OAuth、不接受也不转发 `X-OAuth-Token`，
因此读取授权用户数据只能走本层的直连 HTTP；CLI 仅用于开发期
岛屿选题（hot / search / question answers）与查额度。
"""

from .client import ZhihuClient
from .config import ConfigError, ZhihuSettings, redact
from .errors import (
    AuthError,
    ParamError,
    ProtocolError,
    QuotaExhausted,
    RateLimited,
    RiskRejected,
    UpstreamError,
    ZhihuError,
)
from .importer import (
    EvidenceSignal,
    ImportConsent,
    ImportResult,
    RawSnapshot,
    ZhihuImporter,
    rederive,
)
from .jsonx import parse_next_offset, to_wire_id
from .oauth import InMemoryStateStore, OAuthToken, StateStore, ZhihuOAuth
from .quota import CallBudget, QuotaGate, QuotaItem, QuotaLedger
from .schemas import (
    SIGNAL_WEIGHT,
    STANCE_ELIGIBLE,
    SignalKind,
    UserProfile,
    is_stance_eligible,
)

__all__ = [
    "SIGNAL_WEIGHT",
    "STANCE_ELIGIBLE",
    "AuthError",
    "CallBudget",
    "ConfigError",
    "EvidenceSignal",
    "ImportConsent",
    "ImportResult",
    "InMemoryStateStore",
    "OAuthToken",
    "ParamError",
    "ProtocolError",
    "QuotaExhausted",
    "QuotaGate",
    "QuotaItem",
    "QuotaLedger",
    "RateLimited",
    "RawSnapshot",
    "RiskRejected",
    "SignalKind",
    "StateStore",
    "UpstreamError",
    "UserProfile",
    "ZhihuClient",
    "ZhihuError",
    "ZhihuImporter",
    "ZhihuOAuth",
    "ZhihuSettings",
    "is_stance_eligible",
    "parse_next_offset",
    "redact",
    "rederive",
    "to_wire_id",
]
