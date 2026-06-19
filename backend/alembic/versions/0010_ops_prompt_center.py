"""add ops prompt center tables

Revision ID: 0010_ops_prompt_center
Revises: 0009_agent_ability_configs
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0010_ops_prompt_center"
down_revision: str | None = "0009_agent_ability_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("prompt_templates"):
        op.create_table(
            "prompt_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("scope", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("variables_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("prompt_key", name="uq_prompt_templates_prompt_key"),
        )
        op.create_index("ix_prompt_templates_scope", "prompt_templates", ["scope"])
        op.create_index(
            "ix_prompt_templates_variables_schema_json",
            "prompt_templates",
            ["variables_schema_json"],
            postgresql_using="gin",
        )

    if not _has_table("prompt_versions"):
        op.create_table(
            "prompt_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
        )
        op.create_index("ix_prompt_versions_template_status", "prompt_versions", ["template_id", "status"])
        op.create_index("ix_prompt_versions_checksum", "prompt_versions", ["checksum"])

    if not _has_table("prompt_assignments"):
        op.create_table(
            "prompt_assignments",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("environment", sa.String(length=50), nullable=False, server_default="staging"),
            sa.Column("rollout_percent", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["active_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("prompt_key", "environment", name="uq_prompt_assignments_key_environment"),
        )
        op.create_index("ix_prompt_assignments_environment", "prompt_assignments", ["environment"])

    if not _has_table("prompt_publish_events"):
        op.create_table(
            "prompt_publish_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("from_version_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("to_version_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dry_run_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("published_by", sa.String(length=255), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["from_version_id"], ["prompt_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["to_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_prompt_publish_events_prompt_key_published_at",
            "prompt_publish_events",
            ["prompt_key", "published_at"],
        )
        op.create_index(
            "ix_prompt_publish_events_dry_run_result_json",
            "prompt_publish_events",
            ["dry_run_result_json"],
            postgresql_using="gin",
        )

    if not _has_table("prompt_audit_logs"):
        op.create_table(
            "prompt_audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(length=50), nullable=False),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("actor", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["version_id"], ["prompt_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_prompt_audit_logs_prompt_key_created_at",
            "prompt_audit_logs",
            ["prompt_key", "created_at"],
        )
        op.create_index("ix_prompt_audit_logs_action", "prompt_audit_logs", ["action"])
        op.create_index(
            "ix_prompt_audit_logs_before_json",
            "prompt_audit_logs",
            ["before_json"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_prompt_audit_logs_after_json",
            "prompt_audit_logs",
            ["after_json"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    for table_name in (
        "prompt_audit_logs",
        "prompt_publish_events",
        "prompt_assignments",
        "prompt_versions",
        "prompt_templates",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
