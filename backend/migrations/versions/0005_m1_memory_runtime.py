"""Complete M1 runtime persistence.

Revision ID: 0005_m1_memory_runtime
Revises: 0004_m1_evidence_context
"""
from pathlib import Path
from alembic import op
from sqlalchemy import inspect
import re

revision = "0005_m1_memory_runtime"
down_revision = "0004_m1_evidence_context"
branch_labels = None
depends_on = None


def migration_statements():
    sql = Path(__file__).parents[1].joinpath("0005_m1_memory_runtime.sql").read_text(encoding="utf-8-sig")
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return tuple(s.strip() for s in sql.split(";") if s.strip())


def upgrade():
    bind = op.get_bind()
    for statement in migration_statements():
        # MySQL DDL commits individually. Resume a partially applied migration
        # by checking actual structure, never by stamping an incomplete head.
        column = re.match(r"ALTER TABLE (\w+) ADD COLUMN (\w+)", statement)
        index = re.match(r"ALTER TABLE (\w+) (ADD|DROP) INDEX (\w+)", statement)
        if column and column[2] in {c["name"] for c in inspect(bind).get_columns(column[1])}:
            continue
        if index:
            exists = index[3] in {i["name"] for i in inspect(bind).get_indexes(index[1])}
            if (index[2] == "ADD" and exists) or (index[2] == "DROP" and not exists):
                continue
        op.execute(statement)


def downgrade():
    # Downgrading would discard versioned evidence and break decision replay.
    raise RuntimeError("M1 runtime requires a reviewed forward migration")
