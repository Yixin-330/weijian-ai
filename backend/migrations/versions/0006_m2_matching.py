"""Persist M2 exploration, exclusions, and replayable matching decisions."""
from pathlib import Path
import re
from alembic import op
from sqlalchemy import inspect

revision = "0006_m2_matching"
down_revision = "0005_m1_memory_runtime"
branch_labels = None
depends_on = None


def migration_statements():
    sql = Path(__file__).parents[1].joinpath("0006_m2_matching.sql").read_text(encoding="utf-8-sig")
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return tuple(s.strip() for s in sql.split(";") if s.strip())


def upgrade():
    for statement in migration_statements():
        column = re.match(r"ALTER TABLE (\w+) ADD COLUMN (\w+)", statement)
        if column and column[2] in {c["name"] for c in inspect(op.get_bind()).get_columns(column[1])}:
            continue
        op.execute(statement)


def downgrade():
    raise RuntimeError("Matching decisions require a reviewed forward migration")
