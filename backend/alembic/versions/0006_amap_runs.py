"""add amap run logs

Revision ID: 0006_amap_runs
Revises: 0005_admin_audit_logs
Create Date: 2026-05-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_amap_runs"
down_revision: str | None = "0005_admin_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("amap_poi_search_runs"):
        op.create_table(
            "amap_poi_search_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("keyword", sa.String(length=255), nullable=True),
            sa.Column("types", sa.String(length=255), nullable=True),
            sa.Column("center_lng", sa.Float(), nullable=True),
            sa.Column("center_lat", sa.Float(), nullable=True),
            sa.Column("radius_meters", sa.Integer(), nullable=True),
            sa.Column("limit", sa.Integer(), nullable=True),
            sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_amap_poi_search_runs_agent_run_id", "amap_poi_search_runs", ["agent_run_id"])
        op.create_index(
            "ix_amap_poi_search_runs_status_created_at",
            "amap_poi_search_runs",
            ["status", "created_at"],
        )
        op.create_index(
            "ix_amap_poi_search_runs_request_json",
            "amap_poi_search_runs",
            ["request_json"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_amap_poi_search_runs_response_json",
            "amap_poi_search_runs",
            ["response_json"],
            postgresql_using="gin",
        )

    if not _has_table("amap_poi_candidates"):
        op.create_table(
            "amap_poi_candidates",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("search_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("poi_id", sa.String(length=255), nullable=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), nullable=True),
            sa.Column("typecode", sa.String(length=100), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("lng", sa.Float(), nullable=True),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("distance_meters", sa.Integer(), nullable=True),
            sa.Column("tel", sa.Text(), nullable=True),
            sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["search_run_id"], ["amap_poi_search_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_amap_poi_candidates_search_run_rank",
            "amap_poi_candidates",
            ["search_run_id", "rank"],
        )
        op.create_index("ix_amap_poi_candidates_poi_id", "amap_poi_candidates", ["poi_id"])
        op.create_index("ix_amap_poi_candidates_name", "amap_poi_candidates", ["name"])
        op.create_index(
            "ix_amap_poi_candidates_raw_json",
            "amap_poi_candidates",
            ["raw_json"],
            postgresql_using="gin",
        )

    if not _has_table("amap_route_runs"):
        op.create_table(
            "amap_route_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("mode", sa.String(length=50), nullable=False),
            sa.Column("origin_lng", sa.Float(), nullable=False),
            sa.Column("origin_lat", sa.Float(), nullable=False),
            sa.Column("destination_lng", sa.Float(), nullable=False),
            sa.Column("destination_lat", sa.Float(), nullable=False),
            sa.Column("distance_meters", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("summary_text", sa.Text(), nullable=True),
            sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_amap_route_runs_agent_run_id", "amap_route_runs", ["agent_run_id"])
        op.create_index("ix_amap_route_runs_status_created_at", "amap_route_runs", ["status", "created_at"])
        op.create_index(
            "ix_amap_route_runs_request_json",
            "amap_route_runs",
            ["request_json"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_amap_route_runs_response_json",
            "amap_route_runs",
            ["response_json"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    if _has_table("amap_route_runs"):
        op.drop_table("amap_route_runs")
    if _has_table("amap_poi_candidates"):
        op.drop_table("amap_poi_candidates")
    if _has_table("amap_poi_search_runs"):
        op.drop_table("amap_poi_search_runs")
