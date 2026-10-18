from sqlalchemy import (Table, Column, String, Integer, Boolean, DateTime, JSON,
                        ForeignKey, UniqueConstraint, Index)
from .schema import metadata

matching_guard = Table("matching_guard", metadata,
    Column("id", Integer, primary_key=True))

exploration_states = Table("exploration_states", metadata,
    Column("lifeform_id", String(36), ForeignKey("lifeforms.id"), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False, unique=True),
    Column("island_id", String(64), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("allow_cross_island", Boolean, nullable=False),
    Column("allow_demo_partners", Boolean, nullable=False),
    Column("is_demo", Boolean, nullable=False),
    Column("social_pace", String(32), nullable=False),
    Column("excluded_topics", JSON, nullable=False),
    Column("availability", String(16), nullable=False),
    Column("waiting_since", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("latest_social_snapshot_id", String(36), nullable=True),
    Index("idx_exploration_recall", "island_id", "enabled", "availability", "available_at", "waiting_since"))

pair_exclusions = Table("pair_exclusions", metadata,
    Column("lifeform_id", String(36), ForeignKey("lifeforms.id"), primary_key=True),
    Column("target_lifeform_id", String(36), ForeignKey("lifeforms.id"), primary_key=True),
    Column("decision", String(24), nullable=False),
    Column("until_at", DateTime(timezone=True), nullable=True))

private_encounter_decisions = Table("private_encounter_decisions", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("encounter_id", String(36), ForeignKey("encounters.id"), nullable=False),
    Column("lifeform_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("target_lifeform_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("decision", String(24), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "idempotency_key", name="uq_private_decision_key"))
