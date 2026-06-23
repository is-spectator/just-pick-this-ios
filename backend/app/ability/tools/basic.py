from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.ability.center import AbilityTool
from app.ability.schemas import AbilityContext, ToolResult


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1)


class CardItem(BaseModel):
    title: str = Field(min_length=1)
    subtitle: str | None = None
    category: str | None = None


class DecisionFactor(BaseModel):
    text: str = Field(min_length=1)
    key: str | None = None


class CreateRecommendationCardArgs(BaseModel):
    item: CardItem
    decision_factor: DecisionFactor
    image_asset_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    retrieval_run_id: str | None = None


class HelpContext(BaseModel):
    person: str | None = None
    location: str | None = None
    area: str | None = None
    venue: str | None = None
    scene: str | None = None
    time_window: str | None = None
    party_size: int | None = None


class DraftHelpCardArgs(BaseModel):
    title: str = Field(min_length=1)
    context: HelpContext
    wants: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class HelpCardIdArgs(BaseModel):
    help_card_id: str = Field(min_length=1)


class UpdateHelpCardArgs(HelpCardIdArgs):
    context_text: str | None = None
    title: str | None = None
    wants: list[str] | None = None
    avoids: list[str] | None = None
    constraints: list[str] | None = None


class SubmitOneLinerArgs(HelpCardIdArgs):
    content: str = Field(min_length=1)


class SaveIntentAnswerArgs(BaseModel):
    intent_key: str = Field(min_length=1)
    answer_title: str = Field(min_length=1)
    answer_summary: str = Field(min_length=1)


class LightUserArgs(BaseModel):
    user_id: str = Field(min_length=1)
    type: str = "final_ready"


class SearchKnowledgeAbility(AbilityTool):
    name = "search_knowledge"
    input_model = SearchKnowledgeArgs

    def execute(self, args: BaseModel | dict[str, Any], context: AbilityContext) -> ToolResult:
        data = args.model_dump() if isinstance(args, BaseModel) else dict(args)
        return ToolResult(ok=True, tool_name=self.name, data={"query": data["query"], "hits": []})


class CreateRecommendationCardAbility(AbilityTool):
    name = "create_recommendation_card"
    input_model = CreateRecommendationCardArgs

    def precondition(self, args: BaseModel | dict[str, Any], context: AbilityContext) -> ToolResult | None:
        data = args.model_dump() if isinstance(args, BaseModel) else dict(args)
        if not data.get("evidence_ids"):
            return ToolResult(ok=False, tool_name=self.name, status="failed", error_message="evidence_required")
        return None

    def execute(self, args: BaseModel | dict[str, Any], context: AbilityContext) -> ToolResult:
        data = args.model_dump() if isinstance(args, BaseModel) else dict(args)
        return ToolResult(ok=True, tool_name=self.name, data={"recommendation_card": data})


class DraftHelpCardAbility(AbilityTool):
    name = "draft_help_card"
    input_model = DraftHelpCardArgs

    def precondition(self, args: BaseModel | dict[str, Any], context: AbilityContext) -> ToolResult | None:
        data = args.model_dump() if isinstance(args, BaseModel) else dict(args)
        context_data = data.get("context") or {}
        effective_fields = [value for value in context_data.values() if value not in (None, "", [])]
        if len(effective_fields) < 2:
            return ToolResult(ok=False, tool_name=self.name, status="failed", error_message="weak_help_context")
        return None

    def execute(self, args: BaseModel | dict[str, Any], context: AbilityContext) -> ToolResult:
        data = args.model_dump() if isinstance(args, BaseModel) else dict(args)
        return ToolResult(ok=True, tool_name=self.name, data={"help_card": data})


class UpdateHelpCardAbility(AbilityTool):
    name = "update_help_card"
    input_model = UpdateHelpCardArgs


class PublishHelpCardAbility(AbilityTool):
    name = "publish_help_card"
    input_model = HelpCardIdArgs


class SubmitOneLinerAnswerAbility(AbilityTool):
    name = "submit_one_liner_answer"
    input_model = SubmitOneLinerArgs


class FinalizeHelpCardAbility(AbilityTool):
    name = "finalize_help_card"
    input_model = HelpCardIdArgs


class SaveIntentAnswerAbility(AbilityTool):
    name = "save_intent_answer"
    input_model = SaveIntentAnswerArgs


class LightUserAbility(AbilityTool):
    name = "light_user"
    input_model = LightUserArgs
