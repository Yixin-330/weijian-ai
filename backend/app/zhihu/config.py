"""知乎适配层配置。

凭证只从环境读取，不进入源码、URL、日志、前端响应或 Agent 输出。
App ID 可作为公开配置；App Key 与 Access Secret 不可。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 端点
OPENAPI_BASE = "https://openapi.zhihu.com"
DEVELOPER_BASE = "https://developer.zhihu.com"

AUTHORIZE_URL = f"{OPENAPI_BASE}/authorize"
ACCESS_TOKEN_URL = f"{OPENAPI_BASE}/access_token"
USER_PROFILE_URL = f"{OPENAPI_BASE}/user"

# 用户数据列表接口（需 Access Secret + X-OAuth-Token）
PATH_CONTENTS = "/api/v1/user/contents"
PATH_FOLLOWEES = "/api/v1/user/followees"
PATH_FAVLISTS = "/api/v1/user/favlists"
PATH_FAVLIST_CONTENTS = "/api/v1/user/favlist_contents"
PATH_COLLECTIONS = "/api/v1/user/collections"
PATH_QUOTA = "/api/v1/quota"

# 用户数据列表接口共用的额度组
QUOTA_GROUP_USER_DATA = "user_data"


class ConfigError(RuntimeError):
    """凭证或配置缺失。"""


@dataclass(frozen=True)
class ZhihuSettings:
    """运行期配置。"""

    app_id: str
    app_key: str = field(repr=False)
    redirect_uri: str
    access_secret: str = field(repr=False)

    # 单用户单次导入的调用预算上限（PRD 8.4：4-6 次）。
    import_call_budget: int = 6
    # 低于该剩余额度时闸门直接拒绝导入，留出缓冲避免中途失败。
    quota_floor: int = 10
    # 客户端超时，creator.md 记录服务端默认 10 秒。
    timeout_seconds: float = 10.0
    # state 有效期。
    state_ttl_seconds: int = 600

    def __post_init__(self) -> None:
        if self.import_call_budget < 1:
            raise ConfigError("import_call_budget 必须为正数")
        if self.quota_floor < 0:
            raise ConfigError("quota_floor 不能为负数")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ZhihuSettings":
        src = env if env is not None else dict(os.environ)
        missing = [
            key
            for key in (
                "ZHIHU_OAUTH_APP_ID",
                "ZHIHU_OAUTH_APP_KEY",
                "ZHIHU_OAUTH_REDIRECT_URI",
                "ZHIHU_ACCESS_SECRET",
            )
            if not src.get(key)
        ]
        if missing:
            raise ConfigError(f"缺少环境变量: {', '.join(missing)}")
        return cls(
            app_id=src["ZHIHU_OAUTH_APP_ID"],
            app_key=src["ZHIHU_OAUTH_APP_KEY"],
            redirect_uri=src["ZHIHU_OAUTH_REDIRECT_URI"],
            access_secret=src["ZHIHU_ACCESS_SECRET"],
            import_call_budget=int(src.get("WJ_IMPORT_CALL_BUDGET", "6")),
            quota_floor=int(src.get("WJ_QUOTA_FLOOR", "10")),
        )


def redact(secret: str | None) -> str:
    """日志安全的凭证摘要。永不回显原值。"""
    if not secret:
        return "<unset>"
    return f"<{len(secret)} chars, ...{secret[-2:]}>"
