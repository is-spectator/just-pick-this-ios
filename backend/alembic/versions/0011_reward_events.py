"""add reward events ledger

Revision ID: 0011_reward_events
Revises: 0010_ops_prompt_center
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0011_reward_events"
down_revision: str | None = "0010_ops_prompt_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("reward_events"):
        return

    op.create_table(
        "reward_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("help_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("help_answer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["help_card_id"], ["help_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["help_answer_id"], ["help_answers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reward_events_user_id_created_at", "reward_events", ["user_id", "created_at"])
    op.create_index("ix_reward_events_help_card_id", "reward_events", ["help_card_id"])
    op.create_index("ix_reward_events_help_answer_id", "reward_events", ["help_answer_id"])
    op.create_index("ix_reward_events_status", "reward_events", ["status"])


def downgrade() -> None:
    if _has_table("reward_events"):
        op.drop_table("reward_events")
