"""知乎开放平台错误模型。

平台业务码与 HTTP 状态解耦：HTTP 200 不代表成功，必须同时检查响应体。
参见 references/user-api.md、references/creator.md、references/http-api.md。
"""

from __future__ import annotations


class ZhihuError(Exception):
    """所有平台错误的基类。"""

    retryable = False

    def __init__(self, message: str, *, code: int | None = None, api: str | None = None) -> None:
        self.code = code
        self.api = api
        super().__init__(message)


class ProtocolError(ZhihuError):
    """响应结构与文档契约不符。绝不静默降级或截断。"""


class AuthError(ZhihuError):
    """20001 鉴权失败，或 OAuth token 失效。

    命中后必须停止读取，且不得回退到运营方 Access Secret 所属账号身份。
    """


class ParamError(ZhihuError):
    """10001 参数错误或内容不可用。"""


class RateLimited(ZhihuError):
    """30001 频率、并发或日额度受限。禁止重试。"""


class QuotaExhausted(ZhihuError):
    """30002 配额上限，或本地额度闸门预检拒绝。禁止重试。"""


class RiskRejected(ZhihuError):
    """30003 风控拒绝。"""


class UpstreamError(ZhihuError):
    """90001 服务异常或网络故障。仅幂等 GET 允许有限重试。"""

    retryable = True


# 业务码 -> 异常类型。0 为成功；20000 在 openapi.zhihu.com 上亦表示成功。
_CODE_MAP: dict[int, type[ZhihuError]] = {
    10001: ParamError,
    20001: AuthError,
    30001: RateLimited,
    30002: QuotaExhausted,
    30003: RiskRejected,
    90001: UpstreamError,
}

SUCCESS_CODES = frozenset({0, 20000})


def raise_for_code(code: int, message: str, *, api: str) -> None:
    """把 `developer.zhihu.com` 的业务码映射为异常。

    该端点的错误码有完整文档，因此未知非成功码视为协议偏差，不猜测语义。
    """
    if code in SUCCESS_CODES:
        return
    exc = _CODE_MAP.get(code)
    if exc is None:
        raise ProtocolError(f"未知业务码 {code}: {message}", code=code, api=api)
    raise exc(message or f"业务码 {code}", code=code, api=api)


def raise_for_openapi_code(code: int, message: str, *, api: str) -> None:
    """把 `openapi.zhihu.com` 的业务码映射为异常。

    这套码与 developer 端不同：`20000` 表示成功，`404` 表示用户不存在
    （历史实测为 HTTP 200 + `{"code":404,"data":"User don't exist"}`）。
    oauth.md 待确认项 2 记录该端点的错误响应尚无文档，因此未知码不按
    协议错误处理——授权与身份接口失败在语义上就是鉴权失败，
    调用方应停止读取并请用户重新授权。

    已知的 developer 空间码（如 30001 频率限制）仍按原语义映射，
    以便真的出现时能被正确识别。
    """
    if code in SUCCESS_CODES:
        return
    exc = _CODE_MAP.get(code)
    if exc is not None:
        raise exc(message or f"业务码 {code}", code=code, api=api)
    raise AuthError(message or f"授权失败，业务码 {code}", code=code, api=api)
