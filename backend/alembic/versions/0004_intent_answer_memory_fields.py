"""add intent answer memory fields

Revision ID: 0004_intent_answer_memory
Revises: 0003_card_image_fk
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_intent_answer_memory"
down_revision: str | None = "0003_card_image_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def upgrade() -> None:
    if not _has_column("intent_answers", "intent_key"):
        op.add_column("intent_answers", sa.Column("intent_key", sa.String(length=255), nullable=True))
    if not _has_column("intent_answers", "intent_text"):
        op.add_column("intent_answers", sa.Column("intent_text", sa.Text(), nullable=True))
    if not _has_column("intent_answers", "answer_title"):
        op.add_column("intent_answers", sa.Column("answer_title", sa.Text(), nullable=True))
    if not _has_column("intent_answers", "answer_summary"):
        op.add_column("intent_answers", sa.Column("answer_summary", sa.Text(), nullable=True))
    if not _has_column("intent_answers", "constraints_json"):
        op.add_column(
            "intent_answers",
            sa.Column(
                "constraints_json",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
    if not _has_column("intent_answers", "source_type"):
        op.add_column("intent_answers", sa.Column("source_type", sa.String(length=100), nullable=True))
    if not _has_column("intent_answers", "source_ref_id"):
        op.add_column("intent_answers", sa.Column("source_ref_id", sa.String(length=255), nullable=True))
    if not _has_column("intent_answers", "confidence"):
        op.add_column("intent_answers", sa.Column("confidence", sa.Float(), nullable=True))
    if not _has_column("intent_answers", "success_count"):
        op.add_column(
            "intent_answers",
            sa.Column("success_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        )
    if not _has_column("intent_answers", "rejection_count"):
        op.add_column(
            "intent_answers",
            sa.Column("rejection_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        )
    if not _has_column("intent_answers", "last_used_at"):
        op.add_column("intent_answers", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE intent_answers
        SET intent_key = COALESCE(intent_answers.intent_key, intents.key),
            intent_text = COALESCE(intent_answers.intent_text, intents.name),
            answer_title = COALESCE(intent_answers.answer_title, left(intent_answers.answer_text, 80)),
            answer_summary = COALESCE(intent_answers.answer_summary, intent_answers.answer_text),
            constraints_json = COALESCE(intent_answers.constraints_json, '{}'::jsonb),
            source_type = COALESCE(
                intent_answers.source_type,
                intent_answers.evidence_json ->> 'source_type',
                intent_answers.evidence_json ->> 'source',
                'legacy'
            ),
            source_ref_id = COALESCE(
                intent_answers.source_ref_id,
                intent_answers.evidence_json ->> 'help_card_id',
                intent_answers.evidence_json ->> 'question_id'
            ),
            success_count = COALESCE(intent_answers.success_count, 0),
            rejection_count = COALESCE(intent_answers.rejection_count, 0)
        FROM intents
        WHERE intent_answers.intent_id = intents.id
        """
    )


def downgrade() -> None:
    for column_name in (
        "last_used_at",
        "rejection_count",
        "success_count",
        "confidence",
        "source_ref_id",
        "source_type",
        "constraints_json",
        "answer_summary",
        "answer_title",
        "intent_text",
        "intent_key",
    ):
        if _has_column("intent_answers", column_name):
            op.drop_column("intent_answers", column_name)
