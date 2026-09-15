"""int64 无损处理。

平台的 `uid` 与收藏夹 `UrlToken` 是 int64，可能超出 JavaScript 安全整数范围
(2**53-1)。Python 的 int 是任意精度，解析侧天然安全；风险全部集中在出站边界：
一旦以 JSON 数字发给前端，浏览器会静默丢精度。

因此规则是：入站保持 int，**出站一律转字符串**。
另外请求 `Offset` 是 Int64 而响应 `NextOffset` 是 String，必须严格解析。
"""

from __future__ import annotations

from .errors import ProtocolError

JS_SAFE_MAX = 2**53 - 1


def to_wire_id(value: int | str | None) -> str | None:
    """把 int64 标识转为出站字符串。所有对前端的响应都必须经过这里。"""
    if value is None:
        return None
    return str(value)


def is_js_unsafe(value: int) -> bool:
    """标识是否超出 JavaScript 安全整数范围。"""
    return abs(value) > JS_SAFE_MAX


def parse_next_offset(raw: object, *, api: str) -> int | None:
    """严格解析 `Paging.NextOffset`（响应为 String，回传时作为 Int64）。

    解析失败抛协议错误，不静默截断、不回退为 0。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ProtocolError(f"NextOffset 类型非法: {raw!r}", api=api)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        # 浮点意味着上游或中间层已丢精度，不接受。
        raise ProtocolError(f"NextOffset 为浮点数，可能已丢失精度: {raw!r}", api=api)
    if isinstance(raw, str):
        text = raw.strip()
        try:
            return int(text, 10)
        except ValueError as exc:
            raise ProtocolError(f"NextOffset 无法解析为 Int64: {raw!r}", api=api) from exc
    raise ProtocolError(f"NextOffset 类型非法: {type(raw).__name__}", api=api)
