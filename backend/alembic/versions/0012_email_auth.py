"""add email auth tables

Revision ID: 0012_email_auth
Revises: 0011_reward_events
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0012_email_auth"
down_revision: str | None = "0011_reward_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("users", "email"):
        op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    if not _has_column("users", "email_verified_at"):
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("users", "auth_provider"):
        op.add_column("users", sa.Column("auth_provider", sa.String(length=50), nullable=False, server_default="device"))
    if not _has_column("users", "last_login_at"):
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("users", "status"):
        op.add_column("users", sa.Column("status", sa.String(length=50), nullable=False, server_default="active"))

    if not _has_table("email_login_codes"):
        op.create_table(
            "email_login_codes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("code_hash", sa.String(length=128), nullable=False),
            sa.Column("purpose", sa.String(length=50), nullable=False, server_default="login"),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("request_ip", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("device_uid", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_email_login_codes_email_status_expires_at",
            "email_login_codes",
            ["email", "status", "expires_at"],
        )
        op.create_index("ix_email_login_codes_created_at", "email_login_codes", ["created_at"])

    if not _has_table("auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("device_uid", sa.String(length=255), nullable=True),
            sa.Column("refresh_token_hash", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ip_address", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_auth_sessions_user_id_status", "auth_sessions", ["user_id", "status"])
        op.create_index("ix_auth_sessions_refresh_token_hash", "auth_sessions", ["refresh_token_hash"])

    if not _has_table("auth_audit_logs"):
        op.create_table(
            "auth_audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("ip_address", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_auth_audit_logs_email_created_at", "auth_audit_logs", ["email", "created_at"])
        op.create_index("ix_auth_audit_logs_action_created_at", "auth_audit_logs", ["action", "created_at"])

    if not _has_table("user_devices"):
        op.create_table(
            "user_devices",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("device_uid", sa.String(length=255), nullable=False),
            sa.Column("platform", sa.String(length=50), nullable=True),
            sa.Column("app_version", sa.String(length=50), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "device_uid", name="uq_user_devices_user_id_device_uid"),
        )
        op.create_index("ix_user_devices_device_uid", "user_devices", ["device_uid"])


def downgrade() -> None:
    for table_name in ("user_devices", "auth_audit_logs", "auth_sessions", "email_login_codes"):
        if _has_table(table_name):
            op.drop_table(table_name)
    for column_name in ("status", "last_login_at", "auth_provider", "email_verified_at", "email"):
        if _has_column("users", column_name):
            if column_name == "email":
                op.drop_index("ix_users_email", table_name="users")
            op.drop_column("users", column_name)
