from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine

from app.islands import FixtureError, get_islands, load_island_payload
from app.storage.islands import MySqlIslandCatalog
from app.storage.schema import metadata


def make_catalog(tmp_path) -> MySqlIslandCatalog:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}")
    metadata.create_all(engine)
    return MySqlIslandCatalog(engine)


def test_publish_is_idempotent_and_list_reads_persisted_snapshot(tmp_path):
    catalog = make_catalog(tmp_path)
    assert catalog.check_ready() is False

    first = catalog.publish()
    second = catalog.publish()

    assert first.inserted_islands == 3
    assert first.inserted_fixtures == 3
    assert second.inserted_islands == 0
    assert second.inserted_fixtures == 0
    assert second.unchanged_fixtures == 3
    assert catalog.check_ready() is True

    persisted = catalog.list_islands()
    assert persisted == get_islands()
    assert persisted.ids == ("stability", "intimacy", "ai_loneliness")
    catalog.close()


def test_published_version_is_immutable(tmp_path, monkeypatch):
    catalog = make_catalog(tmp_path)
    catalog.publish()
    changed = deepcopy(load_island_payload())
    changed["islands"][0]["island_name"] = "不允许覆盖的名称"
    monkeypatch.setattr("app.storage.islands.load_island_payload", lambda _: changed)

    with pytest.raises(FixtureError, match="内容哈希发生变化"):
        catalog.publish()
    catalog.close()
