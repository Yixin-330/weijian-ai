from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from app.core.config import Settings
from app.islands import DEFAULT_VERSION
from app.storage import build_island_catalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把版本化问题群岛 fixture 幂等发布到持久化目录",
    )
    parser.add_argument("--version", default=DEFAULT_VERSION)
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.database_url:
        raise SystemExit("WJ_DATABASE_URL 未配置，拒绝把 fixture 发布到内存模式")

    catalog = build_island_catalog(settings)
    try:
        result = catalog.publish(args.version)
        print(json.dumps(asdict(result), ensure_ascii=False))
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
