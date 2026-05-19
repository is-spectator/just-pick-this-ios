import type { Prisma } from "@prisma/client";
import { prisma } from "../db.js";
import { forbidden, notFound } from "../lib/errors.js";
import { normalizeText } from "../lib/time.js";
import { listUsableImageAssets, toCandidateFacts } from "./imageAssetService.js";
import { pipiService } from "./pipi/pipiService.js";
import { findOrCreateCompatUser, findOrCreateUser } from "./userService.js";

export async function submitQuestion(input: {
  deviceUid: string;
  text: string;
  platform?: string;
  appVersion?: string;
}) {
  const user = await findOrCreateUser({
    deviceUid: input.deviceUid,
    platform: input.platform,
    appVersion: input.appVersion,
  });

  const question = await prisma.question.create({
    data: {
      userId: user.id,
      rawText: input.text,
      normalizedText: normalizeText(input.text),
      status: "pipi_processing",
    },
  });

  const imageAssets = await listUsableImageAssets(input.text);
  const decision = await pipiService.decideQuestion({
    question,
    user,
    candidateFacts: toCandidateFacts(imageAssets),
    imageAssets,
  });

  if (decision.kind === "top1") {
    const card = await prisma.top1Card.create({
      data: {
        questionId: question.id,
        userId: user.id,
        source: "pipi_direct",
        title: decision.title,
        subtitle: decision.subtitle,
        reason: decision.reason,
        bullets: decision.bullets as Prisma.InputJsonValue,
        warning: decision.warning,
        imageAssetId: decision.imageAssetId,
        confidence: decision.confidence,
        status: "ready",
      },
      include: { imageAsset: true },
    });

    const updatedQuestion = await prisma.question.update({
      where: { id: question.id },
      data: {
        status: "top1_ready",
        currentCardId: card.id,
      },
    });

    return {
      kind: "top1" as const,
      user,
      question: updatedQuestion,
      card,
    };
  }

  const helpRequest = await prisma.helpRequest.create({
    data: {
      questionId: question.id,
      ownerUserId: user.id,
      title: decision.title,
      contextText: decision.contextText,
      status: "draft",
    },
  });

  const updatedQuestion = await prisma.question.update({
    where: { id: question.id },
    data: {
      status: "ask_draft_ready",
      helpRequestId: helpRequest.id,
    },
  });

  return {
    kind: "ask_draft" as const,
    user,
    question: updatedQuestion,
    helpRequest,
  };
}

export async function submitCompatQuestion(input: {
  sessionId?: string;
  query: string;
}) {
  const user = await findOrCreateCompatUser(input.sessionId);
  const result = await submitQuestion({
    deviceUid: user.deviceUid,
    text: input.query,
    platform: "ios",
    appVersion: "compat",
  });
  return { ...result, sessionId: result.user.id };
}

export async function getQuestion(input: {
  questionId: string;
  deviceUid: string;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });
  const question = await prisma.question.findUnique({
    where: { id: input.questionId },
    include: {
      currentCard: { include: { imageAsset: true } },
      currentHelpRequest: {
        include: {
          answers: { orderBy: { createdAt: "asc" } },
          finalCard: { include: { imageAsset: true } },
        },
      },
    },
  });

  if (!question) {
    throw notFound("Question not found.", "question_not_found");
  }
  if (question.userId !== user.id) {
    throw forbidden("Only the owner can read this question.", "not_question_owner");
  }

  return question;
}

export async function acceptCard(input: {
  cardId: string;
  deviceUid: string;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });
  const card = await prisma.top1Card.findUnique({
    where: { id: input.cardId },
    include: {
      question: true,
    },
  });

  if (!card) {
    throw notFound("Card not found.", "card_not_found");
  }
  if (card.userId !== user.id) {
    throw forbidden("Only the owner can accept this card.", "not_card_owner");
  }

  return acceptCardForUser({
    userId: user.id,
    questionId: card.questionId,
    cardId: card.id,
  });
}

export async function acceptCardForUser(input: {
  userId: string;
  questionId: string;
  cardId?: string | null;
  helpRequestId?: string | null;
}) {
  const question = await prisma.question.findUnique({
    where: { id: input.questionId },
    include: { currentCard: true, currentHelpRequest: true },
  });

  if (!question) {
    throw notFound("Question not found.", "question_not_found");
  }
  if (question.userId !== input.userId) {
    throw forbidden("Only the owner can complete this question.", "not_question_owner");
  }

  const cardId = input.cardId ?? question.currentCardId;
  if (cardId) {
    await prisma.top1Card.update({
      where: { id: cardId },
      data: { status: "accepted" },
    });
  }

  const helpRequestId = input.helpRequestId ?? question.helpRequestId;
  if (helpRequestId) {
    await prisma.helpRequest.update({
      where: { id: helpRequestId },
      data: { status: "closed" },
    });
    await prisma.helpAnswer.updateMany({
      where: { helpRequestId, status: "used" },
      data: { rewardStatus: "granted" },
    });
  }

  return prisma.question.update({
    where: { id: question.id },
    data: { status: "completed" },
  });
}
