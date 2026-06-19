"""add admin audit logs

Revision ID: 0005_admin_audit_logs
Revises: 0004_intent_answer_memory
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0005_admin_audit_logs"
down_revision: str | None = "0004_intent_answer_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("admin_audit_logs"):
        return

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_table", sa.String(length=255), nullable=False),
        sa.Column("target_record_id", sa.String(length=255), nullable=True),
        sa.Column("request_path", sa.Text(), nullable=True),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])
    op.create_index("ix_admin_audit_logs_table_action", "admin_audit_logs", ["target_table", "action"])
    op.create_index("ix_admin_audit_logs_target_record", "admin_audit_logs", ["target_table", "target_record_id"])
    op.create_index(
        "ix_admin_audit_logs_request_json",
        "admin_audit_logs",
        ["request_json"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_admin_audit_logs_before_json",
        "admin_audit_logs",
        ["before_json"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_admin_audit_logs_after_json",
        "admin_audit_logs",
        ["after_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    if _has_table("admin_audit_logs"):
        op.drop_table("admin_audit_logs")
