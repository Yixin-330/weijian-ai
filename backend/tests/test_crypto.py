"""静态数据加密测试。

重点是**上下文绑定**：本模块选 AES-GCM 而非 Fernet 的唯一理由，就是要让
"把用户 A 的 token 密文搬到用户 B 的行"解密失败。若这条不成立，
整个模块退化为普通对称加密，那不如直接用 Fernet。
"""

from __future__ import annotations

import base64

import pytest

from app.core.crypto import (
    PURPOSE_IMPORT_SNAPSHOT,
    PURPOSE_OAUTH_TOKEN,
    CryptoError,
    DecryptionFailed,
    Encryptor,
    KeyRing,
)


def _key() -> bytes:
    return base64.b64decode(KeyRing.generate_key())


def _ring(versions: int = 2) -> KeyRing:
    keys = {v: _key() for v in range(1, versions + 1)}
    return KeyRing(keys=keys, active_version=versions)


def _enc(versions: int = 2) -> Encryptor:
    return Encryptor(_ring(versions))


# ---------- 基本往返 ----------


def test_roundtrip():
    enc = _enc()
    ct = enc.encrypt(b"secret-token", purpose=PURPOSE_OAUTH_TOKEN, binding="user-A")
    assert enc.decrypt(ct, purpose=PURPOSE_OAUTH_TOKEN, binding="user-A") == b"secret-token"


def test_plaintext_absent_from_ciphertext():
    enc = _enc()
    ct = enc.encrypt(b"zhihu-oauth-token", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    assert b"zhihu-oauth-token" not in ct


def test_nonce_is_random_per_call():
    """同明文两次加密必须产生不同密文，否则可从密文相等推断明文相等。"""
    enc = _enc()
    a = enc.encrypt(b"same", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    b = enc.encrypt(b"same", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    assert a != b
    assert enc.decrypt(a, purpose=PURPOSE_OAUTH_TOKEN, binding="u") == b"same"
    assert enc.decrypt(b, purpose=PURPOSE_OAUTH_TOKEN, binding="u") == b"same"


def test_empty_plaintext_supported():
    enc = _enc()
    ct = enc.encrypt(b"", purpose=PURPOSE_IMPORT_SNAPSHOT, binding="u")
    assert enc.decrypt(ct, purpose=PURPOSE_IMPORT_SNAPSHOT, binding="u") == b""


# ---------- 上下文绑定（本模块存在的理由）----------


def test_ciphertext_cannot_be_moved_between_users():
    """行间搬运必须失败。

    威胁模型：拿到写权限的人把 A 的 token 密文塞进 B 的行，
    系统就会用 A 的凭证代表 B 调用平台接口——oauth.md 明令禁止的身份混淆。
    """
    enc = _enc()
    ct = enc.encrypt(b"tok", purpose=PURPOSE_OAUTH_TOKEN, binding="user-A")
    with pytest.raises(DecryptionFailed, match="搬到了不同的用户或用途"):
        enc.decrypt(ct, purpose=PURPOSE_OAUTH_TOKEN, binding="user-B")


def test_ciphertext_cannot_be_reused_across_purposes():
    """oauth token 的密文不能当作导入快照解开，反之亦然。"""
    enc = _enc()
    ct = enc.encrypt(b"tok", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    with pytest.raises(DecryptionFailed):
        enc.decrypt(ct, purpose=PURPOSE_IMPORT_SNAPSHOT, binding="u")


def test_aad_has_no_concatenation_ambiguity():
    """`a|bc` 与 `ab|c` 必须产生不同 AAD，否则边界可被挪动。"""
    enc = _enc()
    ct = enc.encrypt(b"x", purpose="a", binding="bc")
    with pytest.raises(DecryptionFailed):
        enc.decrypt(ct, purpose="ab", binding="c")


def test_empty_binding_rejected():
    """空绑定会让不同行的密文可互换，等于放弃核心保护。"""
    enc = _enc()
    with pytest.raises(CryptoError, match="均不能为空"):
        enc.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="")
    with pytest.raises(CryptoError, match="均不能为空"):
        enc.encrypt(b"x", purpose="", binding="u")


# ---------- 篡改检测 ----------


def test_version_header_downgrade_rejected():
    """改写版本头做降级必须失败：版本号在认证范围内。"""
    enc = _enc()
    ct = bytearray(enc.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u"))
    ct[3:5] = (1).to_bytes(2, "big")  # active 是 2，改成 1
    with pytest.raises(DecryptionFailed):
        enc.decrypt(bytes(ct), purpose=PURPOSE_OAUTH_TOKEN, binding="u")


def test_body_tamper_rejected():
    enc = _enc()
    ct = bytearray(enc.encrypt(b"x" * 32, purpose=PURPOSE_OAUTH_TOKEN, binding="u"))
    ct[-1] ^= 0xFF
    with pytest.raises(DecryptionFailed):
        enc.decrypt(bytes(ct), purpose=PURPOSE_OAUTH_TOKEN, binding="u")


def test_foreign_blob_rejected():
    """不带 WJ1 标识的数据要给出可诊断的错误，而不是模糊的解密失败。"""
    enc = _enc()
    with pytest.raises(DecryptionFailed, match="WJ1"):
        enc.decrypt(b"gAAAAAB" + b"x" * 40, purpose=PURPOSE_OAUTH_TOKEN, binding="u")


def test_truncated_ciphertext_rejected():
    enc = _enc()
    ct = enc.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    with pytest.raises(DecryptionFailed, match="长度不足"):
        enc.decrypt(ct[:10], purpose=PURPOSE_OAUTH_TOKEN, binding="u")


def test_non_bytes_rejected():
    enc = _enc()
    with pytest.raises(DecryptionFailed, match="类型非法"):
        enc.decrypt("not-bytes", purpose=PURPOSE_OAUTH_TOKEN, binding="u")  # type: ignore[arg-type]


# ---------- 密钥轮换 ----------


def test_old_key_data_still_readable_after_rotation():
    """轮换不需要一次性重加密全部历史数据。"""
    k1, k2 = _key(), _key()
    before = Encryptor(KeyRing(keys={1: k1}, active_version=1))
    ct = before.encrypt(b"old-token", purpose=PURPOSE_OAUTH_TOKEN, binding="u")

    after = Encryptor(KeyRing(keys={1: k1, 2: k2}, active_version=2))
    assert after.decrypt(ct, purpose=PURPOSE_OAUTH_TOKEN, binding="u") == b"old-token"


def test_needs_rewrap_flags_stale_key_version():
    k1, k2 = _key(), _key()
    old = Encryptor(KeyRing(keys={1: k1}, active_version=1))
    stale = old.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u")

    enc = Encryptor(KeyRing(keys={1: k1, 2: k2}, active_version=2))
    assert enc.needs_rewrap(stale) is True
    fresh = enc.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    assert enc.needs_rewrap(fresh) is False


def test_removing_in_use_key_gives_actionable_error():
    """移除仍被历史数据引用的旧密钥，错误信息要说清后果。"""
    k1, k2 = _key(), _key()
    old = Encryptor(KeyRing(keys={1: k1}, active_version=1))
    ct = old.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u")

    without_v1 = Encryptor(KeyRing(keys={2: k2}, active_version=2))
    with pytest.raises(DecryptionFailed, match="不能移除仍有历史数据引用的旧版本"):
        without_v1.decrypt(ct, purpose=PURPOSE_OAUTH_TOKEN, binding="u")


def test_active_version_used_for_new_data():
    enc = _enc(versions=3)
    ct = enc.encrypt(b"x", purpose=PURPOSE_OAUTH_TOKEN, binding="u")
    assert enc.key_version_of(ct) == 3 == enc.active_key_version


# ---------- 密钥环校验 ----------


def test_empty_keyring_rejected():
    with pytest.raises(CryptoError, match="密钥环为空"):
        KeyRing(keys={}, active_version=1)


def test_wrong_key_length_rejected():
    with pytest.raises(CryptoError, match="必须为 32"):
        KeyRing(keys={1: b"short"}, active_version=1)


def test_active_version_must_exist():
    with pytest.raises(CryptoError, match="不在密钥环中"):
        KeyRing(keys={1: _key()}, active_version=9)


def test_version_range_enforced():
    """版本号写进 2 字节头部，必须落在 1..65535。"""
    with pytest.raises(CryptoError, match="版本超出范围"):
        KeyRing(keys={0: _key()}, active_version=0)
    with pytest.raises(CryptoError, match="版本超出范围"):
        KeyRing(keys={70000: _key()}, active_version=70000)


def test_keyring_repr_hides_key_material():
    """密钥不得进入日志或异常回溯。"""
    key = _key()
    ring = KeyRing(keys={1: key}, active_version=1)
    text = repr(ring)
    assert base64.b64encode(key).decode() not in text
    assert str(key) not in text
    assert "active=1" in text


def test_generated_key_is_32_bytes():
    assert len(base64.b64decode(KeyRing.generate_key())) == 32
    assert KeyRing.generate_key() != KeyRing.generate_key()


# ---------- 环境变量解析 ----------


def test_from_env_parses_multiple_versions():
    k1, k2 = KeyRing.generate_key(), KeyRing.generate_key()
    ring = KeyRing.from_env({"WJ_ENCRYPTION_KEYS": f"1:{k1},2:{k2}"})
    assert sorted(ring.keys) == [1, 2]
    # 未指定 active 时取最大版本号
    assert ring.active_version == 2


def test_from_env_respects_explicit_active_version():
    k1, k2 = KeyRing.generate_key(), KeyRing.generate_key()
    ring = KeyRing.from_env(
        {
            "WJ_ENCRYPTION_KEYS": f"1:{k1},2:{k2}",
            "WJ_ENCRYPTION_ACTIVE_KEY_VERSION": "1",
        }
    )
    assert ring.active_version == 1


def test_from_env_missing_keys_explains_how_to_generate():
    with pytest.raises(CryptoError, match="generate_key"):
        KeyRing.from_env({})


def test_from_env_rejects_malformed_entries():
    good = KeyRing.generate_key()
    with pytest.raises(CryptoError, match="缺少版本号前缀"):
        KeyRing.from_env({"WJ_ENCRYPTION_KEYS": good})
    with pytest.raises(CryptoError, match="版本号非整数"):
        KeyRing.from_env({"WJ_ENCRYPTION_KEYS": f"v1:{good}"})
    with pytest.raises(CryptoError, match="不是合法 base64"):
        KeyRing.from_env({"WJ_ENCRYPTION_KEYS": "1:not-base64!!"})
    with pytest.raises(CryptoError, match="重复"):
        KeyRing.from_env({"WJ_ENCRYPTION_KEYS": f"1:{good},1:{good}"})


def test_from_env_rejects_short_key():
    short = base64.b64encode(b"tooshort").decode()
    with pytest.raises(CryptoError, match="必须为 32"):
        KeyRing.from_env({"WJ_ENCRYPTION_KEYS": f"1:{short}"})
