"""Create the initial 未见 MVP schema.

Revision ID: 0001_core
Revises: None
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES_IN_DEPENDENCY_ORDER = (
    "users",
    "user_consents",
    "oauth_credentials",
    "import_jobs",
    "lifeforms",
    "platform_import_snapshots",
    "evidence",
    "memories",
    "memory_evidence",
    "memory_revisions",
    "islands",
    "island_fixtures",
    "world_ticks",
    "encounters",
    "encounter_turns",
    "relationships",
    "relationship_events",
    "connections",
    "connection_decisions",
    "chat_channels",
    "icebreakers",
    "agent_runs",
    "audit_events",
)


def migration_statements() -> tuple[str, ...]:
    source = Path(__file__).parents[1].joinpath("0001_core.sql").read_text(
        encoding="utf-8-sig"
    )
    without_comments = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("--")
    )
    return tuple(
        statement.strip()
        for statement in without_comments.split(";")
        if statement.strip()
    )


def upgrade() -> None:
    for statement in migration_statements():
        op.execute(statement)


def downgrade() -> None:
    for table_name in reversed(TABLES_IN_DEPENDENCY_ORDER):
        op.drop_table(table_name)

