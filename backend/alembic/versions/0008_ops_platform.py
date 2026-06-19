"""add ops platform tables

Revision ID: 0008_ops_platform
Revises: 0007_agent_prompt_configs
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008_ops_platform"
down_revision: str | None = "0007_agent_prompt_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("agent_prompt_config_versions"):
        op.create_table(
            "agent_prompt_config_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prompt_config_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("prompt_type", sa.String(length=100), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("change_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["prompt_config_id"], ["agent_prompt_configs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("prompt_key", "version", name="uq_agent_prompt_config_versions_key_version"),
        )
        op.create_index(
            "ix_agent_prompt_config_versions_prompt_key_created_at",
            "agent_prompt_config_versions",
            ["prompt_key", "created_at"],
        )
        op.create_index(
            "ix_agent_prompt_config_versions_config_json",
            "agent_prompt_config_versions",
            ["config_json"],
            postgresql_using="gin",
        )

    if not _has_table("prompt_replay_runs"):
        op.create_table(
            "prompt_replay_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prompt_key", sa.String(length=255), nullable=False),
            sa.Column("prompt_version", sa.Integer(), nullable=True),
            sa.Column("candidate_version", sa.Integer(), nullable=True),
            sa.Column("admin_actor", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_prompt_replay_runs_prompt_key_created_at",
            "prompt_replay_runs",
            ["prompt_key", "created_at"],
        )
        op.create_index(
            "ix_prompt_replay_runs_status_created_at",
            "prompt_replay_runs",
            ["status", "created_at"],
        )
        op.create_index(
            "ix_prompt_replay_runs_input_json",
            "prompt_replay_runs",
            ["input_json"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_prompt_replay_runs_output_json",
            "prompt_replay_runs",
            ["output_json"],
            postgresql_using="gin",
        )

    if not _has_table("ops_metric_snapshots"):
        op.create_table(
            "ops_metric_snapshots",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("bucket", sa.String(length=50), nullable=False),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metric_key", sa.String(length=255), nullable=False),
            sa.Column("dimension_key", sa.String(length=255), nullable=False, server_default="global"),
            sa.Column("metric_value", sa.Float(), nullable=False),
            sa.Column("dimensions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=False, server_default="admin_runtime"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bucket",
                "bucket_start",
                "metric_key",
                "dimension_key",
                name="uq_ops_metric_snapshots_bucket_metric",
            ),
        )
        op.create_index("ix_ops_metric_snapshots_bucket_start", "ops_metric_snapshots", ["bucket", "bucket_start"])
        op.create_index("ix_ops_metric_snapshots_metric_key", "ops_metric_snapshots", ["metric_key"])
        op.create_index(
            "ix_ops_metric_snapshots_dimensions_json",
            "ops_metric_snapshots",
            ["dimensions_json"],
            postgresql_using="gin",
        )

    if not _has_table("content_review_tasks"):
        op.create_table(
            "content_review_tasks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("task_type", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("target_table", sa.String(length=255), nullable=False),
            sa.Column("target_record_id", sa.String(length=255), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_content_review_tasks_status_priority", "content_review_tasks", ["status", "priority"])
        op.create_index(
            "ix_content_review_tasks_task_type_created_at",
            "content_review_tasks",
            ["task_type", "created_at"],
        )
        op.create_index("ix_content_review_tasks_target", "content_review_tasks", ["target_table", "target_record_id"])
        op.create_index(
            "ix_content_review_tasks_payload_json",
            "content_review_tasks",
            ["payload_json"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    for table_name in (
        "content_review_tasks",
        "ops_metric_snapshots",
        "prompt_replay_runs",
        "agent_prompt_config_versions",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
