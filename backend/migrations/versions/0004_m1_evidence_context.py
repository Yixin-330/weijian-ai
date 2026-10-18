"""Add the M1 evidence, understanding-version, and context-snapshot contract.

Revision ID: 0004_m1_evidence_context
Revises: 0003_m0_encounter_count
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "0004_m1_evidence_context"
down_revision: str | None = "0003_m0_encounter_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def migration_statements() -> tuple[str, ...]:
    source = Path(__file__).parents[1].joinpath(
        "0004_m1_evidence_context.sql"
    ).read_text(encoding="utf-8-sig")
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
    op.drop_table("agent_context_snapshots")
    op.execute("ALTER TABLE memories DROP FOREIGN KEY fk_memories_supersedes")
    op.drop_column("memories", "supersedes_memory_id")
    op.drop_column("memories", "version")
    op.execute("ALTER TABLE evidence DROP INDEX uq_evidence_ingestion")
    op.drop_column("evidence", "content_text")
    op.drop_column("evidence", "ingestion_key")
