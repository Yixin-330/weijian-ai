"""知乎登录（Authorization Code Flow）。

两份官方资料在 `state` 上存在冲突：

- `hackathon-oauth.md`：黑客松 OAuth 服务已支持 `state` 原样透传，
  并要求执行完整的 state 校验。
- `oauth.md`：2026-05-14 线上实测**不回传** `state`，且列为待确认项。

本模块按防御性方案实现，两种情况都安全：

1. 主路径校验 `state`（CSPRNG 生成、服务端保存、短 TTL、原子消费一次）。
2. 同时把登录请求绑定到 `HttpOnly` 会话 Cookie。即使平台不回传 state，
   仍可凭 Cookie 确认回调与本浏览器会话的关联性，CSRF 防护不失效。

其他已验证的协议偏差（见 oauth.md「已验证的协议偏差」）：

- 回调参数是 `authorization_code`，不是 `code`；
- 但 token 交换接口的表单字段仍叫 `code`；
- `code: 20000` 表示成功，不能当错误。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from urllib.parse import urlencode

import httpx

from .config import ACCESS_TOKEN_URL, AUTHORIZE_URL, ZhihuSettings
from .errors import AuthError, ProtocolError, raise_for_openapi_code


@dataclass(frozen=True)
class PendingLogin:
    """一次尚未完成的登录请求。"""

    state: str
    browser_session: str
    expires_at: float


@dataclass(frozen=True)
class OAuthToken:
    """用户 OAuth 令牌。

    平台不提供 refresh token、撤销接口或 scope（oauth.md 待确认项 3、4），
    因此过期后只能请用户重新授权。
    """

    access_token: str
    token_type: str
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def __repr__(self) -> str:  # 防止 token 进入日志或异常回溯
        return f"OAuthToken(token_type={self.token_type!r}, expires_at={self.expires_at})"


class StateStore(Protocol):
    """登录请求的服务端存储。

    生产实现用 Redis：`SET state ... EX ttl NX` 写入，`GETDEL` 原子消费。
    """

    def put(self, login: PendingLogin) -> None: ...

    def consume(self, state: str) -> PendingLogin | None:
        """取出并**原子删除**。重复回调第二次必须返回 None。"""


class InMemoryStateStore:
    """单进程 Demo 与测试用实现。多实例或 Serverless 必须换 Redis。"""

    def __init__(self) -> None:
        self._data: dict[str, PendingLogin] = {}
        self._lock = Lock()

    def put(self, login: PendingLogin) -> None:
        with self._lock:
            self._data[login.state] = login

    def consume(self, state: str) -> PendingLogin | None:
        with self._lock:
            login = self._data.pop(state, None)
        if login is None:
            return None
        if time.time() >= login.expires_at:
            return None
        return login


class ZhihuOAuth:
    """授权 URL 构造、回调校验与 Token 交换。"""

    def __init__(
        self,
        settings: ZhihuSettings,
        store: StateStore,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._client = client

    # ---- 发起授权 ----

    def start_login(self) -> tuple[str, str, str]:
        """返回 `(authorize_url, state, browser_session)`。

        调用方须把 `browser_session` 写入 `HttpOnly`、`Secure`、
        `SameSite=Lax` Cookie；`state` 不需要下发给浏览器。
        """
        state = secrets.token_urlsafe(32)
        browser_session = secrets.token_urlsafe(32)
        self._store.put(
            PendingLogin(
                state=state,
                browser_session=browser_session,
                expires_at=time.time() + self._settings.state_ttl_seconds,
            )
        )

        # redirect_uri 在授权与 Token 交换中使用同一个配置值，
        # 结构性保证两处一致（文档要求协议、域名、端口、路径、尾斜杠完全一致）。
        query = urlencode(
            {
                "redirect_uri": self._settings.redirect_uri,
                "app_id": self._settings.app_id,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}", state, browser_session

    # ---- 回调校验 ----

    def verify_callback(
        self,
        *,
        params: dict[str, str],
        cookie_session: str | None,
    ) -> str:
        """校验回调并返回 authorization code。

        `params` 为回调 query。兼容 `authorization_code`（实测主路径）
        与 `code`（可能的协议修订）。
        """
        code = params.get("authorization_code") or params.get("code")
        if not code:
            raise AuthError("回调缺少 authorization_code", api="authorize")

        if not cookie_session:
            raise AuthError("回调缺少会话 Cookie，无法确认请求关联性", api="authorize")

        returned_state = params.get("state")

        if returned_state:
            # 主路径：平台回传了 state。
            login = self._store.consume(returned_state)
            if login is None:
                raise AuthError("state 无效、已过期或已被使用", api="authorize")
            if not secrets.compare_digest(login.browser_session, cookie_session):
                raise AuthError("state 与当前浏览器会话不匹配", api="authorize")
            return code

        # 兜底路径：平台未回传 state（oauth.md 实测）。
        # 改为凭 Cookie 定位本次登录请求，仍然原子消费一次，
        # 因此重复回调依旧会被拒绝。
        login = self._consume_by_session(cookie_session)
        if login is None:
            raise AuthError(
                "回调未携带 state，且未找到与当前会话匹配的待处理登录请求",
                api="authorize",
            )
        return code

    def _consume_by_session(self, cookie_session: str) -> PendingLogin | None:
        """按浏览器会话查找并消费待处理登录请求。

        只有 InMemoryStateStore 暴露了内部字典；Redis 实现应另建
        `session -> state` 的反向索引。
        """
        store = self._store
        if not isinstance(store, InMemoryStateStore):
            raise ProtocolError(
                "当前 StateStore 未提供按会话消费的能力，"
                "无法在平台不回传 state 时安全完成登录",
                api="authorize",
            )
        with store._lock:  # noqa: SLF001 - 同模块内的既定协作
            match = next(
                (
                    login
                    for login in store._data.values()  # noqa: SLF001
                    if secrets.compare_digest(login.browser_session, cookie_session)
                ),
                None,
            )
            if match is not None:
                store._data.pop(match.state, None)  # noqa: SLF001
        if match is None or time.time() >= match.expires_at:
            return None
        return match

    # ---- Token 交换 ----

    async def exchange_token(self, code: str) -> OAuthToken:
        """用授权码换取 access token。

        `app_key` 只在后端提交，绝不出现在浏览器、URL 或日志中。
        """
        form = {
            "app_id": self._settings.app_id,
            "app_key": self._settings.app_key,
            "grant_type": "authorization_code",
            "redirect_uri": self._settings.redirect_uri,
            "code": code,  # 回调参数名是 authorization_code，表单字段仍是 code
        }

        client = self._client or httpx.AsyncClient(timeout=self._settings.timeout_seconds)
        owns_client = self._client is None
        try:
            resp = await client.post(
                ACCESS_TOKEN_URL,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        finally:
            if owns_client:
                await client.aclose()

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProtocolError(
                f"Token 接口返回非 JSON，HTTP {resp.status_code}", api="access_token"
            ) from exc

        if not isinstance(payload, dict):
            raise ProtocolError("Token 接口返回结构非对象", api="access_token")

        # 不能只凭 HTTP 200 判定成功；同时 20000 表示成功不能当错误。
        token = payload.get("access_token")
        if not token:
            code_value = payload.get("code")
            message = str(payload.get("message") or payload.get("data") or "未返回 access_token")
            if isinstance(code_value, int):
                raise_for_openapi_code(code_value, message, api="access_token")
            raise AuthError(f"Token 交换失败: {message}", api="access_token")

        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            # 缺失或非法有效期时不猜测，按最短保守值处理并要求尽早重新授权。
            expires_in = 300

        return OAuthToken(
            access_token=str(token),
            token_type=str(payload.get("token_type") or "Bearer"),
            expires_at=time.time() + expires_in,
        )
