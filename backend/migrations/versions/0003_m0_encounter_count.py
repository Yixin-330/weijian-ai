"""Separate encounter count from the relationship projection version.

Revision ID: 0003_m0_encounter_count
Revises: 0002_m0_domain_contract
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "0003_m0_encounter_count"
down_revision: str | None = "0002_m0_domain_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def migration_statements() -> tuple[str, ...]:
    source = Path(__file__).parents[1].joinpath(
        "0003_m0_encounter_count.sql"
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
    op.drop_column("relationships", "encounter_count")
