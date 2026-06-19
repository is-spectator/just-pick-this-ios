"""optional card images and web search assets

Revision ID: 0002_optional_images
Revises: 0001_database_model_skeleton
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_optional_images"
down_revision: str | None = "0001_database_model_skeleton"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def upgrade() -> None:
    if not _has_table("web_search_runs"):
        op.create_table(
            "web_search_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("search_type", sa.String(length=50), nullable=False),
            sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_web_search_runs")),
        )
    if not _has_index("web_search_runs", "ix_web_search_runs_provider_created_at"):
        op.create_index("ix_web_search_runs_provider_created_at", "web_search_runs", ["provider", "created_at"])
    if not _has_index("web_search_runs", "ix_web_search_runs_query_text"):
        op.create_index("ix_web_search_runs_query_text", "web_search_runs", ["query_text"])
    if not _has_index("web_search_runs", "ix_web_search_runs_response_json"):
        op.create_index(
            "ix_web_search_runs_response_json",
            "web_search_runs",
            ["response_json"],
            postgresql_using="gin",
        )

    if not _has_table("web_search_results"):
        op.create_table(
            "web_search_results",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("web_search_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["web_search_run_id"],
                ["web_search_runs.id"],
                name=op.f("fk_web_search_results_web_search_run_id_web_search_runs"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_web_search_results")),
        )
    if not _has_index("web_search_results", "ix_web_search_results_web_search_run_id"):
        op.create_index("ix_web_search_results_web_search_run_id", "web_search_results", ["web_search_run_id"])
    if not _has_index("web_search_results", "ix_web_search_results_domain"):
        op.create_index("ix_web_search_results_domain", "web_search_results", ["domain"])
    if not _has_index("web_search_results", "ix_web_search_results_raw_json"):
        op.create_index(
            "ix_web_search_results_raw_json",
            "web_search_results",
            ["raw_json"],
            postgresql_using="gin",
        )

    if not _has_column("image_assets", "source_domain"):
        op.add_column("image_assets", sa.Column("source_domain", sa.String(length=255), nullable=True))
    if not _has_column("image_assets", "ai_generated_risk"):
        op.add_column("image_assets", sa.Column("ai_generated_risk", sa.String(length=50), nullable=True))
    if not _has_column("image_assets", "displayable"):
        op.add_column(
            "image_assets",
            sa.Column("displayable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )
    if not _has_column("image_assets", "query_text"):
        op.add_column("image_assets", sa.Column("query_text", sa.Text(), nullable=True))
    if not _has_column("image_assets", "tavily_result_id"):
        op.add_column("image_assets", sa.Column("tavily_result_id", sa.String(length=255), nullable=True))
    if not _has_column("image_assets", "web_search_run_id"):
        op.add_column("image_assets", sa.Column("web_search_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    if not _has_column("image_assets", "license_note"):
        op.add_column("image_assets", sa.Column("license_note", sa.Text(), nullable=True))
    if not _has_foreign_key("image_assets", op.f("fk_image_assets_web_search_run_id_web_search_runs")):
        op.create_foreign_key(
            op.f("fk_image_assets_web_search_run_id_web_search_runs"),
            "image_assets",
            "web_search_runs",
            ["web_search_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_index("image_assets", "ix_image_assets_displayable_verified_non_ai"):
        op.create_index(
            "ix_image_assets_displayable_verified_non_ai",
            "image_assets",
            ["displayable", "verification_status", "is_ai_generated"],
        )
    if not _has_index("image_assets", "ix_image_assets_source_domain"):
        op.create_index("ix_image_assets_source_domain", "image_assets", ["source_domain"])
    if not _has_index("image_assets", "ix_image_assets_web_search_run_id"):
        op.create_index("ix_image_assets_web_search_run_id", "image_assets", ["web_search_run_id"])
    op.execute(
        """
        UPDATE image_assets
        SET displayable = TRUE,
            ai_generated_risk = COALESCE(ai_generated_risk, 'low'),
            source_domain = COALESCE(source_domain, split_part(regexp_replace(source_url, '^https?://(www\\.)?', ''), '/', 1)),
            license_note = COALESCE(license_note, '引用图，仅作识别和购买参考')
        WHERE verified = TRUE
          AND verification_status = 'verified'
          AND is_ai_generated = FALSE
        """
    )

    if not _has_column("recommendation_cards", "image_required"):
        op.add_column(
            "recommendation_cards",
            sa.Column("image_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )
    if not _has_column("recommendation_cards", "image_status"):
        op.add_column(
            "recommendation_cards",
            sa.Column("image_status", sa.String(length=50), server_default="attached", nullable=False),
        )
    op.alter_column("recommendation_cards", "image_asset_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.execute(
        """
        UPDATE recommendation_cards
        SET image_status = CASE WHEN image_asset_id IS NULL THEN 'missing' ELSE 'attached' END
        """
    )


def downgrade() -> None:
    op.alter_column("recommendation_cards", "image_asset_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("recommendation_cards", "image_status")
    op.drop_column("recommendation_cards", "image_required")

    op.drop_index("ix_image_assets_web_search_run_id", table_name="image_assets")
    op.drop_index("ix_image_assets_source_domain", table_name="image_assets")
    op.drop_index("ix_image_assets_displayable_verified_non_ai", table_name="image_assets")
    op.drop_constraint(
        op.f("fk_image_assets_web_search_run_id_web_search_runs"),
        "image_assets",
        type_="foreignkey",
    )
    op.drop_column("image_assets", "license_note")
    op.drop_column("image_assets", "web_search_run_id")
    op.drop_column("image_assets", "tavily_result_id")
    op.drop_column("image_assets", "query_text")
    op.drop_column("image_assets", "displayable")
    op.drop_column("image_assets", "ai_generated_risk")
    op.drop_column("image_assets", "source_domain")

    op.drop_index("ix_web_search_results_raw_json", table_name="web_search_results")
    op.drop_index("ix_web_search_results_domain", table_name="web_search_results")
    op.drop_index("ix_web_search_results_web_search_run_id", table_name="web_search_results")
    op.drop_table("web_search_results")

    op.drop_index("ix_web_search_runs_response_json", table_name="web_search_runs")
    op.drop_index("ix_web_search_runs_query_text", table_name="web_search_runs")
    op.drop_index("ix_web_search_runs_provider_created_at", table_name="web_search_runs")
    op.drop_table("web_search_runs")
