"""add hot reload agent prompt configs

Revision ID: 0007_agent_prompt_configs
Revises: 0006_amap_runs
Create Date: 2026-05-25
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_agent_prompt_configs"
down_revision: str | None = "0006_amap_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("agent_prompt_configs"):
        op.create_table(
            "agent_prompt_configs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("prompt_type", sa.String(length=100), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key", name="uq_agent_prompt_configs_key"),
        )
        op.create_index(
            "ix_agent_prompt_configs_key_enabled",
            "agent_prompt_configs",
            ["key", "enabled"],
        )
        op.create_index("ix_agent_prompt_configs_prompt_type", "agent_prompt_configs", ["prompt_type"])
        op.create_index(
            "ix_agent_prompt_configs_config_json",
            "agent_prompt_configs",
            ["config_json"],
            postgresql_using="gin",
        )

    prompt_table = sa.table(
        "agent_prompt_configs",
        sa.column("id", postgresql.UUID),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("prompt_type", sa.String),
        sa.column("content", sa.Text),
        sa.column("config_json", postgresql.JSONB),
        sa.column("version", sa.Integer),
        sa.column("enabled", sa.Boolean),
        sa.column("updated_by", sa.String),
        sa.column("notes", sa.Text),
    )
    existing = op.get_bind().execute(
        sa.text("select 1 from agent_prompt_configs where key = :key"),
        {"key": "area_food_evidence_policy"},
    ).first()
    if existing is None:
        op.bulk_insert(
            prompt_table,
            [
                {
                    "id": uuid.uuid4(),
                    "key": "area_food_evidence_policy",
                    "name": "到区域选店证据策略",
                    "prompt_type": "evidence_policy",
                    "content": (
                        "你是皮皮的到区域选店证据策略。先尊重用户显式偏好和身份线索，"
                        "再考虑距离。用户说广东人/粤/广州/深圳时，不要把湘菜、川菜、"
                        "重辣火锅当作默认答案；应优先搜索并选择粤菜、广式、潮汕、茶餐厅、顺德等更匹配的 POI。"
                    ),
                    "config_json": {
                        "generic_food_keyword": "餐饮",
                        "profile_cuisine_rules": [
                            {
                                "name": "cantonese_profile",
                                "when_any": ["广东人", "广州人", "深圳人", "粤", "广东口味"],
                                "search_keyword": "粤菜",
                                "display_food": "粤菜",
                                "decision_prefix": "你说自己是广东人，先按粤菜/清淡口味筛一遍。",
                                "prefer_terms": ["粤", "广东", "广州", "潮汕", "茶餐厅", "广式", "顺德", "港式"],
                                "reject_terms": ["长沙", "湘菜", "川菜", "麻辣", "重辣", "火锅"],
                                "require_preferred_match": True,
                            }
                        ],
                    },
                    "version": 1,
                    "enabled": True,
                    "updated_by": "migration",
                    "notes": "运营后台可实时修改；下一次 /v1/chat/turn 会直接读取最新配置。",
                }
            ],
        )


def downgrade() -> None:
    if _has_table("agent_prompt_configs"):
        op.drop_table("agent_prompt_configs")
