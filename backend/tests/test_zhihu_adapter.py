"""知乎适配层的安全属性测试。

覆盖 PRD 19.1 中与适配层相关的用例：
TC-IMP-001/002/003/004、TC-AUTH-001/002、TC-MEM-004。

未安装 pytest-asyncio，异步用例统一用 asyncio.run 驱动。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.zhihu import (
    AuthError,
    ImportConsent,
    InMemoryStateStore,
    ProtocolError,
    QuotaExhausted,
    QuotaGate,
    QuotaItem,
    QuotaLedger,
    RawSnapshot,
    SignalKind,
    ZhihuClient,
    ZhihuImporter,
    ZhihuOAuth,
    ZhihuSettings,
    is_stance_eligible,
    parse_next_offset,
    rederive,
)
from app.zhihu.jsonx import JS_SAFE_MAX
from app.zhihu.schemas import FavlistRecord, Paging, drop_sensitive

SETTINGS = ZhihuSettings(
    app_id="app-1",
    app_key="key-1",
    redirect_uri="https://example.test/callback",
    access_secret="secret-1",
)

# 超出 JS 安全整数范围的真实量级 ID
BIG_UID = 969570047710216200
BIG_FAVLIST = 9007199254740999


def make_gate(*, budget: int = 6, floor: int = 10) -> QuotaGate:
    return QuotaGate(QuotaLedger(), budget=budget, floor=floor)


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- int64 无损（TC-IMP-002）----------


def test_big_uid_exceeds_js_safe_range():
    """确认测试用的 ID 确实超出 JS 安全范围，否则这组用例没有意义。"""
    assert BIG_UID > JS_SAFE_MAX
    assert BIG_FAVLIST > JS_SAFE_MAX


def test_favlist_token_parsed_losslessly():
    fav = FavlistRecord.parse(
        {"UrlToken": BIG_FAVLIST, "Title": "要不要换条路", "Description": "", "IsPublic": True},
        api="test",
    )
    assert fav.url_token == BIG_FAVLIST
    # 出站必须是字符串，否则浏览器会静默丢精度
    assert fav.wire_token == "9007199254740999"
    assert isinstance(fav.wire_token, str)


def test_float_token_rejected_not_truncated():
    """浮点意味着上游已丢精度，必须报错而非静默接受。"""
    with pytest.raises(ProtocolError, match="丢失精度"):
        FavlistRecord.parse({"UrlToken": 9.007199254741e15, "Title": "x"}, api="test")


def test_profile_uid_kept_as_string():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人", "gender": "male"})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            return await c.get_user_profile("tok")

    profile = asyncio.run(run())
    assert profile.uid == "969570047710216200"
    assert isinstance(profile.uid, str)


# ---------- 分页严格解析 ----------


def test_next_offset_string_parsed_as_int():
    assert parse_next_offset("40", api="t") == 40


def test_next_offset_garbage_raises():
    with pytest.raises(ProtocolError):
        parse_next_offset("abc", api="t")


def test_next_offset_float_rejected():
    with pytest.raises(ProtocolError):
        parse_next_offset(40.0, api="t")


def test_paging_incomplete_stops_traversal():
    """IsEnd=false 但缺 NextOffset 属于分页信息不完整，必须停止而非按条数推算。"""
    paging = Paging.parse({"IsEnd": False, "Totals": 100}, api="t")
    with pytest.raises(ProtocolError, match="分页信息不完整"):
        paging.next_or_stop(api="t")


def test_paging_end_returns_none():
    paging = Paging.parse({"IsEnd": True, "Totals": 3}, api="t")
    assert paging.next_or_stop(api="t") is None


# ---------- 敏感属性排除（TC-MATCH-001）----------


def test_gender_dropped_at_ingress():
    """性别不得进入数据流，而不是留到打分阶段跳过。"""
    clean = drop_sensitive(
        {"Fullname": "某人", "Gender": 2, "Headline": "hi", "Author": {"Name": "a", "Gender": 1}}
    )
    assert "Gender" not in clean
    assert "Gender" not in clean["Author"]
    assert clean["Headline"] == "hi"


def test_profile_sensitive_fields_dropped():
    clean = drop_sensitive({"uid": 1, "gender": "male", "email": "a@b.c", "phone_no": "138"})
    assert set(clean) == {"uid"}


# ---------- 立场来源白名单（TC-MEM-004）----------


def test_only_authored_content_carries_stance():
    assert is_stance_eligible(SignalKind.AUTHORED_CONTENT)
    # 收藏一篇内容完全可能是为了反驳它
    assert not is_stance_eligible(SignalKind.FAVORITE_ITEM)
    assert not is_stance_eligible(SignalKind.FAVLIST_NAMING)
    assert not is_stance_eligible(SignalKind.FOLLOWEE_HEADLINE)


# ---------- state 校验（TC-AUTH-001）----------


def test_valid_state_accepted():
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    url, state, session = oauth.start_login()
    assert f"app_id={SETTINGS.app_id}" in url
    assert f"state={state}" in url
    code = oauth.verify_callback(
        params={"authorization_code": "c1", "state": state}, cookie_session=session
    )
    assert code == "c1"


def test_replayed_state_rejected():
    """原子消费一次：重复回调必须失败。"""
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, state, session = oauth.start_login()
    oauth.verify_callback(params={"authorization_code": "c1", "state": state}, cookie_session=session)
    with pytest.raises(AuthError, match="已被使用|无效"):
        oauth.verify_callback(
            params={"authorization_code": "c1", "state": state}, cookie_session=session
        )


def test_forged_state_rejected():
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, _state, session = oauth.start_login()
    with pytest.raises(AuthError):
        oauth.verify_callback(
            params={"authorization_code": "c1", "state": "forged"}, cookie_session=session
        )


def test_state_from_other_browser_session_rejected():
    """不同浏览器会话不能复用登录请求。"""
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, state, _session = oauth.start_login()
    with pytest.raises(AuthError, match="不匹配"):
        oauth.verify_callback(
            params={"authorization_code": "c1", "state": state}, cookie_session="attacker"
        )


def test_expired_state_rejected():
    store = InMemoryStateStore()
    oauth = ZhihuOAuth(SETTINGS, store)
    _url, state, session = oauth.start_login()
    # 手动过期
    pending = store._data[state]
    store._data[state] = type(pending)(
        state=pending.state, browser_session=pending.browser_session, expires_at=time.time() - 1
    )
    with pytest.raises(AuthError):
        oauth.verify_callback(
            params={"authorization_code": "c1", "state": state}, cookie_session=session
        )


def test_missing_cookie_rejected():
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, state, _session = oauth.start_login()
    with pytest.raises(AuthError, match="Cookie"):
        oauth.verify_callback(
            params={"authorization_code": "c1", "state": state}, cookie_session=None
        )


def test_callback_without_state_falls_back_to_cookie():
    """平台实测不回传 state 时，仍凭 Cookie 保持 CSRF 防护且只能用一次。"""
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, _state, session = oauth.start_login()
    code = oauth.verify_callback(params={"authorization_code": "c1"}, cookie_session=session)
    assert code == "c1"
    with pytest.raises(AuthError):
        oauth.verify_callback(params={"authorization_code": "c1"}, cookie_session=session)


def test_callback_accepts_legacy_code_param():
    oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore())
    _url, state, session = oauth.start_login()
    assert (
        oauth.verify_callback(params={"code": "c9", "state": state}, cookie_session=session) == "c9"
    )


def test_token_never_repr_leaked():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"app_key=key-1" in request.content  # app_key 只在后端提交
        return httpx.Response(200, json={"access_token": "s3cret", "expires_in": 3600})

    async def run():
        oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore(), client=mock_client(handler))
        return await oauth.exchange_token("c1")

    token = asyncio.run(run())
    assert token.access_token == "s3cret"
    assert "s3cret" not in repr(token)  # 防止 token 进入日志或异常回溯


def test_token_exchange_code_20000_is_success():
    """20000 表示成功，不能当错误。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 20000, "access_token": "t", "expires_in": 60})

    async def run():
        oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore(), client=mock_client(handler))
        return await oauth.exchange_token("c1")

    assert asyncio.run(run()).access_token == "t"


def test_http_200_without_token_is_failure():
    """不能只凭 HTTP 200 判定成功。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 404, "data": "User don't exist"})

    async def run():
        oauth = ZhihuOAuth(SETTINGS, InMemoryStateStore(), client=mock_client(handler))
        return await oauth.exchange_token("c1")

    with pytest.raises(AuthError):
        asyncio.run(run())


# ---------- 两套错误码空间不得混用 ----------


def test_openapi_unknown_code_is_auth_error_not_protocol_error():
    """openapi 端点的错误响应无文档（oauth.md 待确认项 2）。

    未知码按鉴权失败处理，让调用方停止读取并请用户重新授权；
    若误按 developer 端映射，404 会落进「未知业务码」而变成 ProtocolError。
    """
    from app.zhihu.errors import raise_for_openapi_code

    with pytest.raises(AuthError):
        raise_for_openapi_code(404, "User don't exist", api="t")
    with pytest.raises(AuthError):
        raise_for_openapi_code(99999, "unknown", api="t")


def test_openapi_code_20000_is_success():
    from app.zhihu.errors import raise_for_openapi_code

    raise_for_openapi_code(20000, "", api="t")
    raise_for_openapi_code(0, "", api="t")


def test_openapi_still_maps_known_platform_codes():
    """已知的 developer 空间码若真的出现，仍按原语义识别。"""
    from app.zhihu.errors import RateLimited, raise_for_openapi_code

    with pytest.raises(RateLimited):
        raise_for_openapi_code(30001, "rate limit exceeded", api="t")


def test_developer_unknown_code_stays_protocol_error():
    """developer 端错误码有完整文档，未知码属协议偏差，不猜语义。"""
    from app.zhihu.errors import raise_for_code

    with pytest.raises(ProtocolError, match="未知业务码"):
        raise_for_code(404, "User don't exist", api="t")


# ---------- 额度闸门（TC-IMP-001）----------


def test_quota_gate_rejects_before_any_call():
    gate = make_gate(budget=6, floor=10)
    items = [QuotaItem("user_data", "知乎用户数据", 100, 92, 8)]
    with pytest.raises(QuotaExhausted, match="导入已取消"):
        gate.preflight(items)


def test_quota_gate_allows_sufficient():
    gate = make_gate(budget=6, floor=10)
    gate.preflight([QuotaItem("user_data", "知乎用户数据", 100, 10, 90)])


def test_quota_gate_rejects_when_group_absent():
    """查不到额度组时不假设充足。"""
    gate = make_gate()
    with pytest.raises(QuotaExhausted, match="无法确认余量"):
        gate.preflight([QuotaItem("creator", "创作能力", 100, 0, 100)])


def test_import_aborts_before_business_calls_when_quota_low():
    """额度不足时，除基础信息与额度查询外不得发出任何业务调用。"""
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "openapi.zhihu.com":
            return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})
        if request.url.path.endswith("/quota"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": [
                        {
                            "APIID": "user_data",
                            "APIName": "知乎用户数据",
                            "TotalQuota": 100,
                            "TotalUsed": 95,
                            "RemainingQuota": 5,
                        }
                    ],
                },
            )
        raise AssertionError(f"额度不足时不应调用业务接口: {request.url.path}")

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            importer = ZhihuImporter(c, make_gate(), SETTINGS)
            return await importer.run(
                oauth_token="tok", consent=ImportConsent(authored_content=True)
            )

    with pytest.raises(QuotaExhausted):
        asyncio.run(run())
    assert not any("user/contents" in p for p in calls)


# ---------- 调用预算（PRD 8.4）----------


def test_import_stops_at_budget_and_keeps_partial_data():
    """超预算时停止并保留已获数据，不抛异常丢弃成果。"""
    business_calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "openapi.zhihu.com":
            return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})
        if path.endswith("/quota"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": [
                        {
                            "APIID": "user_data",
                            "APIName": "知乎用户数据",
                            "TotalQuota": 500,
                            "TotalUsed": 0,
                            "RemainingQuota": 500,
                        }
                    ],
                },
            )
        business_calls.append(path)
        if path.endswith("contents"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": {
                        "Items": [
                            {
                                "ContentType": "answer",
                                "Url": "https://www.zhihu.com/answer/1",
                                "CreatedAt": 1757000000,
                                "Title": "关于职业选择",
                                "Summary": "我最近在想要不要换条路",
                            }
                        ],
                        "Paging": {"IsEnd": True, "Totals": 1},
                    },
                },
            )
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": []}})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            # 预算只给 1 次：contents 用掉后，收藏与关注都应放弃
            importer = ZhihuImporter(c, make_gate(budget=1, floor=0), SETTINGS)
            return await importer.run(
                oauth_token="tok",
                consent=ImportConsent(authored_content=True, favorites=True, followees=True),
            )

    result = asyncio.run(run())
    assert result.calls_spent == 1
    assert result.budget_exhausted
    assert "预算" in (result.partial_reason or "")
    # 已获数据保留
    assert len(result.signals) == 1
    assert result.signals[0].kind == SignalKind.AUTHORED_CONTENT
    assert result.has_authored_evidence
    assert len([p for p in business_calls if "user/" in p]) == 1


def test_consent_gates_each_source():
    """未开启的导入项一次调用都不发。"""
    business: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openapi.zhihu.com":
            return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})
        if request.url.path.endswith("/quota"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": [
                        {
                            "APIID": "user_data",
                            "APIName": "知乎用户数据",
                            "TotalQuota": 500,
                            "TotalUsed": 0,
                            "RemainingQuota": 500,
                        }
                    ],
                },
            )
        business.append(request.url.path)
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": []}})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            importer = ZhihuImporter(c, make_gate(), SETTINGS)
            return await importer.run(
                oauth_token="tok", consent=ImportConsent(followees=True)
            )

    asyncio.run(run())
    assert all("followees" in p for p in business)
    assert not any("contents" in p or "favlist" in p for p in business)


def test_no_consent_skips_quota_and_business_calls():
    """完全不授权的用户不产生任何额度消耗，创建流程不被阻塞。"""
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            importer = ZhihuImporter(c, make_gate(), SETTINGS)
            return await importer.run(oauth_token="tok", consent=ImportConsent())

    result = asyncio.run(run())
    assert result.profile is not None
    assert result.snapshots == []
    assert not any("quota" in p for p in paths)


# ---------- 鉴权失败不得降级（TC-AUTH-002）----------


def test_auth_failure_propagates_and_never_retries_without_oauth_header():
    """OAuth token 失效时停止读取，绝不去掉 X-OAuth-Token 重试。"""
    seen_headers: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openapi.zhihu.com":
            return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})
        if request.url.path.endswith("/quota"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": [
                        {
                            "APIID": "user_data",
                            "APIName": "知乎用户数据",
                            "TotalQuota": 500,
                            "TotalUsed": 0,
                            "RemainingQuota": 500,
                        }
                    ],
                },
            )
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"Code": 20001, "Message": "auth failed"})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            importer = ZhihuImporter(c, make_gate(), SETTINGS)
            return await importer.run(
                oauth_token="tok", consent=ImportConsent(authored_content=True)
            )

    with pytest.raises(AuthError):
        asyncio.run(run())
    # 只尝试一次，且每次都带着 X-OAuth-Token
    assert len(seen_headers) == 1
    assert seen_headers[0].get("x-oauth-token") == "tok"


def test_rate_limit_keeps_partial_and_does_not_retry():
    """30001 命中后立即停止，不重试，保留已获数据。"""
    hits: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openapi.zhihu.com":
            return httpx.Response(200, json={"uid": BIG_UID, "fullname": "某人"})
        if request.url.path.endswith("/quota"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": [
                        {
                            "APIID": "user_data",
                            "APIName": "知乎用户数据",
                            "TotalQuota": 500,
                            "TotalUsed": 0,
                            "RemainingQuota": 500,
                        }
                    ],
                },
            )
        hits.append(request.url.path)
        if request.url.path.endswith("contents"):
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Data": {
                        "Items": [
                            {
                                "ContentType": "answer",
                                "Url": "https://www.zhihu.com/answer/1",
                                "CreatedAt": 1757000000,
                                "Title": "标题",
                                "Summary": "摘要",
                            }
                        ],
                        "Paging": {"IsEnd": True},
                    },
                },
            )
        return httpx.Response(200, json={"Code": 30001, "Message": "rate limit exceeded"})

    async def run():
        async with ZhihuClient(SETTINGS, client=mock_client(handler)) as c:
            importer = ZhihuImporter(c, make_gate(), SETTINGS)
            return await importer.run(
                oauth_token="tok",
                consent=ImportConsent(authored_content=True, favorites=True),
            )

    result = asyncio.run(run())
    assert "受限" in (result.partial_reason or "")
    assert len(result.signals) == 1  # contents 的成果保留
    # favlists 命中限流后不再继续 collections
    assert sum(1 for p in hits if "favlist" in p or "collections" in p) == 1


# ---------- 快照复用（TC-IMP-003）----------


def test_rederive_makes_no_network_calls():
    """调整规则后可重跑历史数据，不消耗租户级日额度。"""
    snapshots = [
        RawSnapshot(
            api="user/contents",
            path="/api/v1/user/contents",
            params={},
            items=[
                {
                    "ContentType": "answer",
                    "Url": "https://www.zhihu.com/answer/1",
                    "CreatedAt": 1757000000,
                    "Title": "关于职业选择",
                    "Summary": "在想要不要换条路",
                }
            ],
        ),
        RawSnapshot(
            api="user/favlists",
            path="/api/v1/user/favlists",
            params={},
            items=[
                {
                    "UrlToken": BIG_FAVLIST,
                    "Title": "要不要换条路",
                    "Description": "关于选择",
                    "IsPublic": True,
                }
            ],
        ),
    ]
    signals = rederive(snapshots)
    kinds = {s.kind for s in signals}
    assert kinds == {SignalKind.AUTHORED_CONTENT, SignalKind.FAVLIST_NAMING}
    assert [signal.snapshot_index for signal in signals] == [0, 1]
    # 收藏夹 token 在派生结果里仍是无损字符串
    fav = next(s for s in signals if s.kind == SignalKind.FAVLIST_NAMING)
    assert fav.source_url == f"favlist:{BIG_FAVLIST}"


def test_favorite_uses_fav_time_not_created_at():
    """收藏时间才代表用户行为时刻，用于跨自然日判定。"""
    snapshots = [
        RawSnapshot(
            api="user/collections",
            path="/api/v1/user/collections",
            params={},
            items=[
                {
                    "ContentType": "article",
                    "Url": "https://zhuanlan.zhihu.com/p/1",
                    "CreatedAt": 1600000000,
                    "FavTime": 1757000000,
                    "Title": "创业",
                    "Summary": "摘要",
                }
            ],
        )
    ]
    signal = rederive(snapshots)[0]
    assert signal.occurred_at == 1757000000
    assert signal.snapshot_index == 0
