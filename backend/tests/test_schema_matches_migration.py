"""运行时投影与迁移 SQL 的一致性。

## 为什么需要这个测试

`app/storage/schema.py` 是运行时投影，`migrations/0001_core.sql` 是结构契约，
两者是**同一张表的两份声明**。而现有测试用 `metadata.create_all()` 按投影建表，
根本不读迁移 SQL——因此投影里写错列名、漏列、写出迁移中不存在的列，
测试全部照常通过，直到真正连上 MySQL 才炸。

这不是假想风险：本文件添加时，四张导入表的投影里有六处错误
（`fetched_at` 实为 `imported_at`、凭空多出 `request_params`／`item_count`／
`external_uid`／`quota_group`、`oauth_credentials` 主键写成独立 `id`），
现有测试一个都没发现。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.storage.schema import metadata

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "0001_core.sql"

_NON_COLUMN_PREFIXES = (
    "CONSTRAINT",
    "UNIQUE KEY",
    "KEY ",
    "PRIMARY KEY",
    "INDEX",
    "FULLTEXT",
)


def _migration_table_columns() -> dict[str, list[str]]:
    """解析迁移 SQL，返回每张表的列名顺序。"""
    sql = MIGRATION.read_text(encoding="utf-8")
    tables: dict[str, list[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS ([a-z_]+) \((.*?)\n\) ENGINE", sql, re.S
    ):
        name, body = match.group(1), match.group(2)
        columns = []
        for line in body.splitlines():
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.startswith(_NON_COLUMN_PREFIXES):
                continue
            columns.append(stripped.split()[0])
        tables[name] = columns
    return tables


MIGRATION_TABLES = _migration_table_columns()


def test_migration_parses():
    """解析器本身要有效，否则后续断言会因空数据而假通过。"""
    assert len(MIGRATION_TABLES) >= 20
    assert "users" in MIGRATION_TABLES
    assert "id" in MIGRATION_TABLES["users"]


@pytest.mark.parametrize("table_name", sorted(metadata.tables))
def test_projected_table_exists_in_migration(table_name: str):
    """投影的每张表都必须在迁移中存在。"""
    assert table_name in MIGRATION_TABLES, (
        f"{table_name} 在投影中存在但迁移里没有；"
        "运行时表结构必须由迁移创建，不能只存在于 SQLAlchemy 投影里。"
    )


@pytest.mark.parametrize("table_name", sorted(metadata.tables))
def test_projected_columns_exist_in_migration(table_name: str):
    """投影里的列不得是迁移中不存在的列。

    反向不检查：投影是**子集**，只映射运行时用到的热列，
    这是 schema.py 顶部注释的既定设计。
    """
    if table_name not in MIGRATION_TABLES:
        pytest.skip("缺表由另一个用例报告")
    migration_columns = set(MIGRATION_TABLES[table_name])
    projected = [c.name for c in metadata.tables[table_name].columns]
    unknown = [c for c in projected if c not in migration_columns]
    assert not unknown, (
        f"{table_name} 投影中的列在迁移里不存在: {unknown}；"
        f"迁移实际列为 {sorted(migration_columns)}"
    )


def test_import_tables_are_projected():
    """导入闭环依赖的四张表必须已投影，否则第四步无法落库。"""
    for table_name in (
        "user_consents",
        "oauth_credentials",
        "import_jobs",
        "platform_import_snapshots",
    ):
        assert table_name in metadata.tables


def test_encounter_runtime_tables_are_projected():
    for table_name in ("encounters", "encounter_turns", "relationship_events"):
        assert table_name in metadata.tables


def test_ciphertext_columns_are_binary():
    """密文列必须是二进制类型。

    若被声明成 String，AES-GCM 密文在某些驱动下会被当文本处理并损坏。
    """
    from sqlalchemy import LargeBinary

    for table_name, column_name in (
        ("oauth_credentials", "access_token_ciphertext"),
        ("oauth_credentials", "refresh_token_ciphertext"),
        ("platform_import_snapshots", "raw_response_ciphertext"),
    ):
        column = metadata.tables[table_name].columns[column_name]
        assert isinstance(column.type, LargeBinary), (
            f"{table_name}.{column_name} 类型为 {column.type!r}，应为 LargeBinary"
        )


def test_deletable_snapshot_ciphertext_is_nullable():
    """`chk_deleted_snapshot_erased` 要求删除态清空密文，因此该列必须可为 NULL。"""
    column = metadata.tables["platform_import_snapshots"].columns[
        "raw_response_ciphertext"
    ]
    assert column.nullable is True


def test_oauth_credentials_keyed_by_user():
    """一个用户对一个 provider 只保留一份有效凭证。"""
    primary_keys = [c.name for c in metadata.tables["oauth_credentials"].primary_key]
    assert primary_keys == ["user_id"]


def test_import_idempotency_constraint_present():
    """重复提交同一导入请求必须复用同一 job，而不是再花一遍租户额度。"""
    names = {c.name for c in metadata.tables["import_jobs"].constraints if c.name}
    assert "uq_import_job_idempotency" in names


def test_snapshot_dedup_constraint_present():
    """同一用户、同一接口、同一内容只存一份快照。"""
    names = {
        c.name for c in metadata.tables["platform_import_snapshots"].constraints if c.name
    }
    assert "uq_import_snapshot_hash" in names
