import type {
  HelpAnswer,
  HelpRequest,
  ImageAsset,
  LightEvent,
  Question,
  Top1Card,
  User,
} from "@prisma/client";

export function serializeUser(user: User) {
  return {
    id: user.id,
    device_uid: user.deviceUid,
    display_name: user.displayName,
    platform: user.platform,
    app_version: user.appVersion,
    created_at: user.createdAt.toISOString(),
    last_seen_at: user.lastSeenAt.toISOString(),
  };
}

export function serializeQuestion(question: Question) {
  return {
    id: question.id,
    user_id: question.userId,
    raw_text: question.rawText,
    normalized_text: question.normalizedText,
    status: question.status,
    current_card_id: question.currentCardId,
    help_request_id: question.helpRequestId,
    created_at: question.createdAt.toISOString(),
    updated_at: question.updatedAt.toISOString(),
  };
}

export function serializeImageAsset(asset: ImageAsset) {
  return {
    id: asset.id,
    source_type: asset.sourceType,
    url: asset.url,
    thumbnail_url: asset.thumbnailUrl,
    source_url: asset.sourceUrl,
    credit: asset.credit,
    is_ai_generated: asset.isAiGenerated,
    verification_status: asset.verificationStatus,
    place_key: asset.placeKey,
    item_key: asset.itemKey,
    created_at: asset.createdAt.toISOString(),
  };
}

export function serializeCard(card: Top1Card & { imageAsset?: ImageAsset }) {
  return {
    id: card.id,
    question_id: card.questionId,
    user_id: card.userId,
    source: card.source,
    title: card.title,
    subtitle: card.subtitle,
    reason: card.reason,
    bullets: card.bullets,
    warning: card.warning,
    image_asset_id: card.imageAssetId,
    image_asset: card.imageAsset ? serializeImageAsset(card.imageAsset) : undefined,
    confidence: card.confidence,
    status: card.status,
    created_at: card.createdAt.toISOString(),
  };
}

export function serializeHelpRequest(
  helpRequest: HelpRequest & {
    answers?: HelpAnswer[];
    finalCard?: (Top1Card & { imageAsset?: ImageAsset }) | null;
  },
) {
  return {
    id: helpRequest.id,
    question_id: helpRequest.questionId,
    owner_user_id: helpRequest.ownerUserId,
    title: helpRequest.title,
    context_text: helpRequest.contextText,
    status: helpRequest.status,
    answer_count: helpRequest.answerCount,
    min_answers_required: helpRequest.minAnswersRequired,
    final_card_id: helpRequest.finalCardId,
    final_card: helpRequest.finalCard ? serializeCard(helpRequest.finalCard) : undefined,
    answers: helpRequest.answers?.map(serializeAnswer),
    published_at: helpRequest.publishedAt?.toISOString(),
    final_ready_at: helpRequest.finalReadyAt?.toISOString(),
    created_at: helpRequest.createdAt.toISOString(),
    updated_at: helpRequest.updatedAt.toISOString(),
  };
}

export function serializeAnswer(answer: HelpAnswer) {
  return {
    id: answer.id,
    help_request_id: answer.helpRequestId,
    answer_user_id: answer.answerUserId,
    raw_text: answer.rawText,
    normalized_text: answer.normalizedText,
    status: answer.status,
    reward_status: answer.rewardStatus,
    created_at: answer.createdAt.toISOString(),
  };
}

export function serializeLightEvent(event: LightEvent) {
  return {
    id: event.id,
    user_id: event.userId,
    question_id: event.questionId,
    help_request_id: event.helpRequestId,
    card_id: event.cardId,
    type: event.type,
    title: event.title,
    body: event.body,
    lit_at: event.litAt.toISOString(),
    expires_at: event.expiresAt?.toISOString(),
    seen_at: event.seenAt?.toISOString(),
    created_at: event.createdAt.toISOString(),
  };
}

export function serializeCompatHistory(question: Question & { currentCard?: Top1Card | null }) {
  return {
    id: question.id,
    query: question.rawText,
    status: compatQuestionStatus(question.status),
    helpRequestId: question.helpRequestId,
    topPick: question.currentCard ? serializeCompatTopPick(question.currentCard, question.rawText) : undefined,
  };
}

export function serializeCompatTopPick(card: Top1Card, query: string) {
  return {
    query,
    preface: "别查了,就这个。",
    title: card.title,
    subtitle: card.subtitle,
    reason: card.reason,
    bullets: card.bullets,
    warning: card.warning ?? "",
    followups: ["为什么?", "换个小众的"],
  };
}

export function serializeCompatHelpRequest(
  helpRequest: HelpRequest & {
    answers?: HelpAnswer[];
  },
) {
  return {
    id: helpRequest.id,
    title: helpRequest.title,
    context: helpRequest.contextText,
    status: compatHelpStatus(helpRequest.status),
    answers: helpRequest.answers?.map((answer) => ({
      id: answer.id,
      text: answer.rawText,
      nickname: "路过的人",
      timeLabel: "刚刚",
    })) ?? [],
  };
}

function compatQuestionStatus(status: string) {
  switch (status) {
  case "top1_ready":
  case "final_ready":
    return "top1";
  case "ask_draft_ready":
  case "help_published":
  case "collecting_answers":
    return "waiting_for_human";
  case "completed":
    return "completed";
  default:
    return status;
  }
}

function compatHelpStatus(status: string) {
  switch (status) {
  case "published":
  case "collecting":
    return "published";
  case "final_ready":
    return "answered";
  case "closed":
    return "completed";
  default:
    return status;
  }
}
