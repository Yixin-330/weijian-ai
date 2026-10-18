"""Freeze the M0 encounter, decision, and connection contract.

Revision ID: 0002_m0_domain_contract
Revises: 0001_core
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "0002_m0_domain_contract"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def migration_statements() -> tuple[str, ...]:
    source = Path(__file__).parents[1].joinpath(
        "0002_m0_domain_contract.sql"
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
    op.drop_table("messages")
    op.drop_table("encounter_decisions")
    op.execute("ALTER TABLE connections DROP CHECK chk_connection_status")
    op.execute(
        "UPDATE connections SET status = CASE "
        "WHEN status = 'waiting' THEN 'pending' "
        "WHEN status IN ('mutual_accepted', 'active') THEN 'mutual_accepted' "
        "ELSE 'revoked' END"
    )
    op.execute(
        "ALTER TABLE connections ADD CONSTRAINT chk_connection_status "
        "CHECK (status IN ('pending', 'mutual_accepted', 'declined', "
        "'expired', 'revoked'))"
    )
    op.execute(
        "ALTER TABLE relationship_events "
        "RENAME COLUMN committed_status TO committed_stage"
    )
    op.execute(
        "ALTER TABLE relationship_events "
        "RENAME COLUMN proposed_status TO proposed_stage"
    )
    op.execute(
        "ALTER TABLE relationship_events "
        "RENAME COLUMN previous_status TO previous_stage"
    )
    op.execute("ALTER TABLE relationships DROP CHECK chk_relationship_status")
    op.execute("ALTER TABLE relationships RENAME COLUMN status TO current_stage")
    op.execute(
        "UPDATE relationships SET current_stage = CASE "
        "WHEN current_stage = 'ended' THEN 'ended' ELSE 'shared_experience' END"
    )
    op.execute(
        "ALTER TABLE relationships ADD CONSTRAINT chk_relationship_stage "
        "CHECK (current_stage IN ('unmet', 'noticed', 'shared_experience', "
        "'cared', 'connection_candidate', 'stalled', 'distant', 'ended'))"
    )
