from __future__ import annotations

from sqlalchemy import create_engine

from app.core.config import Settings
from app.domain.experience import ExperienceModule
from app.domain.interface import Experience
from app.domain.island_catalog import FixtureIslandCatalog, IslandCatalog

from .islands import MySqlIslandCatalog
from .mysql import MySqlExperienceModule


def build_experience(settings: Settings) -> Experience:
    if not settings.database_url:
        return ExperienceModule()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    return MySqlExperienceModule(engine)


def build_island_catalog(settings: Settings) -> IslandCatalog:
    if not settings.database_url:
        return FixtureIslandCatalog()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    return MySqlIslandCatalog(engine)
