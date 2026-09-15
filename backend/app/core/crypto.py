"""静态数据加密。

用途：`oauth_credentials.access_token_ciphertext` 与
`platform_import_snapshots.raw_response_ciphertext`。两者都是
`LONGBLOB NOT NULL`／`NULL`，因此本模块直接产出 bytes，不做 base64 包装。

## 为什么用 AES-GCM 而不是 Fernet

Fernet 更简单，但无法绑定上下文。这里的威胁不只是"数据库被读"，还有
**行间搬运**：拿到写权限的人把用户 A 的 token 密文塞进用户 B 的行，
Fernet 会正常解密，系统就用 A 的凭证代表 B 调用平台接口——正是
`oauth.md` 明令禁止的身份混淆。

AES-GCM 支持 AAD（附加认证数据），把 `purpose` 与 `binding`（通常是
user_id）绑进认证范围。搬运后的密文解密直接失败，而不是安静地成功。

## 密钥轮换

密文头部携带密钥版本，因此轮换不需要一次性重加密全部历史数据：
新数据用 active 版本加密，旧数据仍能用旧版本密钥解开。这是
`WJ_ENCRYPTION_KEYS` 支持多版本的原因。
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 密文布局：MAGIC(3) || key_version(2, big-endian) || nonce(12) || ct+tag
MAGIC = b"WJ1"
_VERSION_BYTES = 2
_NONCE_BYTES = 12
_HEADER_LEN = len(MAGIC) + _VERSION_BYTES
_KEY_BYTES = 32  # AES-256

# 用途标签。写进 AAD，使不同用途的密文不能互换。
PURPOSE_OAUTH_TOKEN = "oauth_access_token"
PURPOSE_IMPORT_SNAPSHOT = "platform_import_snapshot"


class CryptoError(RuntimeError):
    """密钥配置错误。"""


class DecryptionFailed(CryptoError):
    """密文损坏、密钥缺失，或上下文绑定不匹配。

    绑定不匹配意味着密文被搬到了别的用户或用途下，属于安全事件，
    调用方不应重试，也不应回退到"跳过解密"继续流程。
    """


@dataclass(frozen=True)
class KeyRing:
    """版本化密钥环。

    `keys` 至少包含一项；`active_version` 指明新数据用哪个版本加密。
    """

    keys: dict[int, bytes]
    active_version: int

    def __post_init__(self) -> None:
        if not self.keys:
            raise CryptoError("密钥环为空")
        for version, key in self.keys.items():
            if not 1 <= version <= 0xFFFF:
                raise CryptoError(f"密钥版本超出范围: {version}")
            if len(key) != _KEY_BYTES:
                raise CryptoError(
                    f"密钥版本 {version} 长度为 {len(key)} 字节，必须为 {_KEY_BYTES}"
                )
        if self.active_version not in self.keys:
            raise CryptoError(f"active 版本 {self.active_version} 不在密钥环中")

    def __repr__(self) -> str:  # 防止密钥材料进入日志或异常回溯
        return (
            f"KeyRing(versions={sorted(self.keys)}, active={self.active_version})"
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "KeyRing":
        """从环境读取。

        `WJ_ENCRYPTION_KEYS` 形如 `1:<base64>,2:<base64>`；
        `WJ_ENCRYPTION_ACTIVE_KEY_VERSION` 缺省时取最大版本号。
        """
        src = env if env is not None else dict(os.environ)
        raw = (src.get("WJ_ENCRYPTION_KEYS") or "").strip()
        if not raw:
            raise CryptoError(
                "缺少 WJ_ENCRYPTION_KEYS。生成方式见 KeyRing.generate_key()，"
                "格式为 `版本号:base64密钥`，多个以逗号分隔。"
            )

        keys: dict[int, bytes] = {}
        for chunk in raw.split(","):
            item = chunk.strip()
            if not item:
                continue
            if ":" not in item:
                raise CryptoError(f"密钥项缺少版本号前缀: {item[:8]}...")
            version_text, _, key_text = item.partition(":")
            try:
                version = int(version_text.strip(), 10)
            except ValueError as exc:
                raise CryptoError(f"密钥版本号非整数: {version_text!r}") from exc
            try:
                key = base64.b64decode(key_text.strip(), validate=True)
            except Exception as exc:  # base64 的异常类型随实现而异
                raise CryptoError(f"密钥版本 {version} 不是合法 base64") from exc
            if version in keys:
                raise CryptoError(f"密钥版本 {version} 重复")
            keys[version] = key

        active_text = (src.get("WJ_ENCRYPTION_ACTIVE_KEY_VERSION") or "").strip()
        if active_text:
            try:
                active = int(active_text, 10)
            except ValueError as exc:
                raise CryptoError(
                    f"WJ_ENCRYPTION_ACTIVE_KEY_VERSION 非整数: {active_text!r}"
                ) from exc
        else:
            active = max(keys)

        return cls(keys=keys, active_version=active)

    @staticmethod
    def generate_key() -> str:
        """生成一个新的 base64 密钥，供运维写入环境变量。"""
        return base64.b64encode(secrets.token_bytes(_KEY_BYTES)).decode("ascii")


def _aad(*, key_version: int, purpose: str, binding: str) -> bytes:
    """构造附加认证数据。

    把 MAGIC 与密钥版本一起纳入认证范围，防止攻击者改写版本头做降级；
    `purpose` 与 `binding` 之间用 0x00 分隔，避免拼接歧义
    （`a|bc` 与 `ab|c` 必须产生不同的 AAD）。
    """
    header = MAGIC + key_version.to_bytes(_VERSION_BYTES, "big")
    return header + purpose.encode("utf-8") + b"\x00" + binding.encode("utf-8")


class Encryptor:
    """绑定上下文的 AES-GCM 加解密器。"""

    def __init__(self, keyring: KeyRing) -> None:
        self._keyring = keyring

    @property
    def active_key_version(self) -> int:
        return self._keyring.active_version

    def encrypt(self, plaintext: bytes, *, purpose: str, binding: str) -> bytes:
        """加密。`binding` 通常是 user_id。

        `purpose` 与 `binding` 不进入密文，只进入认证范围——解密时必须
        提供完全相同的值，因此调用方不能"猜"出别人的上下文。
        """
        if not purpose or not binding:
            # 空绑定会让不同行的密文可互换，等于放弃了本模块的核心保护。
            raise CryptoError("purpose 与 binding 均不能为空")
        version = self._keyring.active_version
        key = self._keyring.keys[version]
        nonce = secrets.token_bytes(_NONCE_BYTES)
        blob = AESGCM(key).encrypt(
            nonce, plaintext, _aad(key_version=version, purpose=purpose, binding=binding)
        )
        return MAGIC + version.to_bytes(_VERSION_BYTES, "big") + nonce + blob

    def decrypt(self, ciphertext: bytes, *, purpose: str, binding: str) -> bytes:
        """解密。上下文不匹配时抛 `DecryptionFailed`，不返回部分结果。"""
        if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
            raise DecryptionFailed(f"密文类型非法: {type(ciphertext).__name__}")
        data = bytes(ciphertext)
        if len(data) < _HEADER_LEN + _NONCE_BYTES:
            raise DecryptionFailed("密文长度不足，无法包含头部与 nonce")
        if not data.startswith(MAGIC):
            raise DecryptionFailed("密文缺少 WJ1 标识，可能不是本系统写入的数据")

        version = int.from_bytes(data[len(MAGIC) : _HEADER_LEN], "big")
        key = self._keyring.keys.get(version)
        if key is None:
            raise DecryptionFailed(
                f"密文使用密钥版本 {version}，但密钥环中没有该版本；"
                "轮换密钥时不能移除仍有历史数据引用的旧版本。"
            )

        nonce = data[_HEADER_LEN : _HEADER_LEN + _NONCE_BYTES]
        blob = data[_HEADER_LEN + _NONCE_BYTES :]
        try:
            return AESGCM(key).decrypt(
                nonce, blob, _aad(key_version=version, purpose=purpose, binding=binding)
            )
        except InvalidTag as exc:
            raise DecryptionFailed(
                "解密认证失败：密文已损坏，或被搬到了不同的用户或用途下。"
            ) from exc

    def key_version_of(self, ciphertext: bytes) -> int:
        """读取密文所用的密钥版本，用于判断哪些行需要重加密。"""
        data = bytes(ciphertext)
        if len(data) < _HEADER_LEN or not data.startswith(MAGIC):
            raise DecryptionFailed("密文头部非法")
        return int.from_bytes(data[len(MAGIC) : _HEADER_LEN], "big")

    def needs_rewrap(self, ciphertext: bytes) -> bool:
        """该密文是否用的是非 active 密钥。"""
        return self.key_version_of(ciphertext) != self._keyring.active_version
