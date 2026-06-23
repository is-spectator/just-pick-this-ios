"""add user behavior events ledger

Revision ID: 0013_user_behavior_events
Revises: 0012_email_auth
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0013_user_behavior_events"
down_revision: str | None = "0012_email_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("user_behavior_events"):
        return

    op.create_table(
        "user_behavior_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("help_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("help_answer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False, server_default="api"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_card_id"], ["recommendation_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["help_card_id"], ["help_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["help_answer_id"], ["help_answers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_behavior_events_user_id_created_at", "user_behavior_events", ["user_id", "created_at"])
    op.create_index(
        "ix_user_behavior_events_event_type_created_at",
        "user_behavior_events",
        ["event_type", "created_at"],
    )
    op.create_index("ix_user_behavior_events_conversation_id", "user_behavior_events", ["conversation_id"])
    op.create_index(
        "ix_user_behavior_events_recommendation_card_id",
        "user_behavior_events",
        ["recommendation_card_id"],
    )
    op.create_index("ix_user_behavior_events_help_card_id", "user_behavior_events", ["help_card_id"])
    op.create_index(
        "ix_user_behavior_events_payload_json",
        "user_behavior_events",
        ["payload_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    if _has_table("user_behavior_events"):
        op.drop_table("user_behavior_events")
