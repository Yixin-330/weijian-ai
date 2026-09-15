"""用户数据 API 客户端。

鉴权模型（user-api.md 身份模型）：

- `Authorization: Bearer <access_secret>` 鉴权**调用方**，每次请求必带；
- `X-OAuth-Token: <oauth_access_token>` 指明当前**被代表的用户**；
- `X-Request-Timestamp: <unix_seconds>` 必带。

关键约束：OAuth token 失效时停止读取，**绝不去掉 `X-OAuth-Token` 重试**——
那会静默切换成运营方 Access Secret 所属账号的身份，等于拿运营者自己的
数据冒充用户（oauth.md 安全要求明令禁止）。

CLI 不发起 OAuth、不接受也不转发 `X-OAuth-Token`，因此后端读取授权用户
数据只能走本模块的直连 HTTP；CLI 仅用于开发期选题与查额度。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .config import (
    DEVELOPER_BASE,
    PATH_QUOTA,
    USER_PROFILE_URL,
    ZhihuSettings,
)
from .errors import (
    AuthError,
    ProtocolError,
    UpstreamError,
    raise_for_code,
    raise_for_openapi_code,
)
from .quota import QuotaItem
from .schemas import Paging, UserProfile, drop_sensitive


class ZhihuClient:
    """薄客户端：只负责鉴权、协议校验与错误映射，不含业务编排。"""

    def __init__(
        self,
        settings: ZhihuSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "ZhihuClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._settings.timeout_seconds)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ZhihuClient 必须在 async with 上下文中使用")
        return self._client

    def _platform_headers(self, oauth_token: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        }
        if oauth_token:
            headers["X-OAuth-Token"] = oauth_token
        return headers

    # ---- 底层请求 ----

    async def _get_json(
        self,
        url: str,
        *,
        api: str,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> Any:
        client = self._require_client()
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise UpstreamError(f"{api} 请求超时", api=api) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{api} 网络错误: {exc}", api=api) from exc

        if resp.status_code in (401, 403):
            raise AuthError(f"{api} 鉴权失败，HTTP {resp.status_code}", api=api)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProtocolError(
                f"{api} 返回非 JSON，HTTP {resp.status_code}", api=api
            ) from exc
        return payload

    async def _get_platform_data(
        self,
        path: str,
        *,
        api: str,
        oauth_token: str,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """调用 developer.zhihu.com 的用户数据接口并解包 `Data`。"""
        payload = await self._get_json(
            f"{DEVELOPER_BASE}{path}",
            api=api,
            headers=self._platform_headers(oauth_token),
            params=params,
        )
        if not isinstance(payload, dict):
            raise ProtocolError(f"{api} 响应结构非对象", api=api)

        # 同时检查 HTTP 状态与业务码；HTTP 200 不代表成功。
        code = payload.get("Code")
        if not isinstance(code, int):
            raise ProtocolError(f"{api} 缺少 Code 字段", api=api)
        raise_for_code(code, str(payload.get("Message") or ""), api=api)

        data = payload.get("Data")
        if not isinstance(data, dict):
            raise ProtocolError(f"{api} Data 结构非对象", api=api)
        return drop_sensitive(data)

    @staticmethod
    def _items(data: dict, *, api: str) -> list[dict]:
        items = data.get("Items")
        if items is None:
            return []
        if not isinstance(items, list):
            raise ProtocolError(f"{api} Items 结构非数组", api=api)
        return [i for i in items if isinstance(i, dict)]

    # ---- 额度 ----

    async def get_quota(self, api_ids: list[str] | None = None) -> list[QuotaItem]:
        """查询额度。该查询本身不消耗业务额度，可在导入前安全调用。"""
        api = "quota"
        params = {"APIIDs": ",".join(api_ids)} if api_ids else None
        payload = await self._get_json(
            f"{DEVELOPER_BASE}{PATH_QUOTA}",
            api=api,
            headers=self._platform_headers(None),
            params=params,
        )
        if not isinstance(payload, dict):
            raise ProtocolError("quota 响应结构非对象", api=api)
        code = payload.get("Code")
        if not isinstance(code, int):
            raise ProtocolError("quota 缺少 Code 字段", api=api)
        raise_for_code(code, str(payload.get("Message") or ""), api=api)

        data = payload.get("Data")
        if not isinstance(data, list):
            raise ProtocolError("quota Data 结构非数组", api=api)

        out: list[QuotaItem] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            out.append(
                QuotaItem(
                    api_id=str(raw.get("APIID") or ""),
                    api_name=str(raw.get("APIName") or ""),
                    total=int(raw.get("TotalQuota") or 0),
                    used=int(raw.get("TotalUsed") or 0),
                    remaining=int(raw.get("RemainingQuota") or 0),
                )
            )
        return out

    # ---- 基础信息（只需 OAuth token）----

    async def get_user_profile(self, oauth_token: str) -> UserProfile:
        """获取授权用户基础信息。

        该接口只用 OAuth token，不需要 Access Secret、`X-OAuth-Token`
        或请求时间戳，且不属于 `user_data` 额度组。
        """
        api = "openapi/user"
        payload = await self._get_json(
            USER_PROFILE_URL,
            api=api,
            headers={"Authorization": f"Bearer {oauth_token}"},
        )
        if not isinstance(payload, dict):
            raise ProtocolError("基础信息响应结构非对象", api=api)

        # 该接口不返回 Code 时以用户对象是否存在为准；
        # 20000 表示成功，不能当错误。历史错误形态为 HTTP 200 + code 404。
        if "uid" not in payload:
            code = payload.get("code")
            message = str(payload.get("data") or payload.get("message") or "未返回用户信息")
            if isinstance(code, int):
                # openapi 端点的码空间与 developer 端不同（20000 成功、404 用户不存在）。
                raise_for_openapi_code(code, message, api=api)
            raise AuthError(f"基础信息缺少用户标识: {message}", api=api)

        return UserProfile.parse(drop_sensitive(payload), api=api)

    # ---- 用户数据列表（单页；翻页由导入编排层控制预算）----

    async def list_page(
        self,
        path: str,
        *,
        api: str,
        oauth_token: str,
        params: dict[str, Any],
        paged: bool = True,
    ) -> tuple[list[dict], Paging | None]:
        """取一页列表数据。

        `favlists` 与 `collections` 没有 Paging（服务端忽略 Offset），
        对它们传 `paged=False`，并且不得把返回结果当作完整历史。
        """
        data = await self._get_platform_data(
            path, api=api, oauth_token=oauth_token, params=params
        )
        items = self._items(data, api=api)
        if not paged:
            return items, None
        raw_paging = data.get("Paging")
        if raw_paging is None:
            raise ProtocolError(f"{api} 缺少 Paging", api=api)
        return items, Paging.parse(raw_paging, api=api)
