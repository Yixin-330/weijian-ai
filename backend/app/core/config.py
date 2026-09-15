from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


_BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    app_name: str = "未见后端"
    demo_admin_token: str = "local-demo-only"
    database_url: str | None = None
    redis_url: str | None = None
    tick_queue_name: str = "weijian:ticks"
    tick_cron_minutes: int = 10
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    )
    # 静态加密密钥环的原始配置值，格式见 app/core/crypto.py 的 KeyRing.from_env。
    # 刻意保存原始字符串而不是解析后的密钥：解析后的 KeyRing 含密钥材料，
    # 不应放进会被日志或异常回溯打印的 Settings。
    encryption_keys: str | None = None
    encryption_active_key_version: str | None = None

    def keyring(self):
        """构造密钥环。缺少配置时报错，而不是回退到不加密。

        延迟到真正需要加密时才校验：本地开发即使没配密钥，
        也能启动服务体验不涉及导入的功能。
        """
        from .crypto import CryptoError, KeyRing

        if not self.encryption_keys:
            raise CryptoError(
                "未配置 WJ_ENCRYPTION_KEYS，无法加密存储 OAuth 令牌与导入快照。"
                "生成方式：python -c \"from app.core.crypto import KeyRing;"
                " print(KeyRing.generate_key())\"，再以 `1:<密钥>` 写入环境变量。"
            )
        env = {"WJ_ENCRYPTION_KEYS": self.encryption_keys}
        if self.encryption_active_key_version:
            env["WJ_ENCRYPTION_ACTIVE_KEY_VERSION"] = self.encryption_active_key_version
        return KeyRing.from_env(env)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(_BACKEND_ENV_FILE, override=False)
        environment = os.getenv("WJ_ENVIRONMENT", "development")
        demo_admin_token = os.getenv("WJ_DEMO_ADMIN_TOKEN", "local-demo-only")
        if environment == "production" and demo_admin_token == "local-demo-only":
            raise RuntimeError("WJ_DEMO_ADMIN_TOKEN must be configured in production")
        encryption_keys = os.getenv("WJ_ENCRYPTION_KEYS")
        if environment == "production" and not encryption_keys:
            # 生产环境不允许以未加密方式落地凭证，缺密钥直接拒绝启动。
            raise RuntimeError("WJ_ENCRYPTION_KEYS must be configured in production")
        tick_cron_minutes = int(os.getenv("WJ_TICK_CRON_MINUTES", "10"))
        if not 1 <= tick_cron_minutes <= 60:
            raise RuntimeError("WJ_TICK_CRON_MINUTES must be between 1 and 60")
        cors_origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "WJ_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,"
                "http://127.0.0.1:4173,http://localhost:4173",
            ).split(",")
            if origin.strip()
        )
        return cls(
            environment=environment,
            demo_admin_token=demo_admin_token,
            database_url=os.getenv("WJ_DATABASE_URL"),
            redis_url=os.getenv("WJ_REDIS_URL"),
            tick_queue_name=os.getenv("WJ_TICK_QUEUE_NAME", "weijian:ticks"),
            tick_cron_minutes=tick_cron_minutes,
            cors_origins=cors_origins,
            encryption_keys=encryption_keys,
            encryption_active_key_version=os.getenv("WJ_ENCRYPTION_ACTIVE_KEY_VERSION"),
        )
