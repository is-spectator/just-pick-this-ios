"""add agent ability configs

Revision ID: 0009_agent_ability_configs
Revises: 0008_ops_platform
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0009_agent_ability_configs"
down_revision: str | None = "0008_ops_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("agent_ability_configs"):
        return
    op.create_table(
        "agent_ability_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ability_type", sa.String(length=100), nullable=False, server_default="builtin_tool"),
        sa.Column("tool_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("runtime_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_intents_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_contract_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("guardrails_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_keys_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_agent_ability_configs_key"),
    )
    op.create_index("ix_agent_ability_configs_key_enabled", "agent_ability_configs", ["key", "enabled"])
    op.create_index("ix_agent_ability_configs_tool_name", "agent_ability_configs", ["tool_name"])
    op.create_index("ix_agent_ability_configs_ability_type", "agent_ability_configs", ["ability_type"])
    op.create_index(
        "ix_agent_ability_configs_trigger_intents_json",
        "agent_ability_configs",
        ["trigger_intents_json"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_agent_ability_configs_config_json",
        "agent_ability_configs",
        ["config_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    if _has_table("agent_ability_configs"):
        op.drop_table("agent_ability_configs")
