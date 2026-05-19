import type { Prisma } from "@prisma/client";
import { prisma } from "../db.js";
import { notFound } from "../lib/errors.js";
import { listUsableImageAssets } from "./imageAssetService.js";
import { pipiService } from "./pipi/pipiService.js";

export async function finalizeHelpRequest(helpRequestId: string) {
  const helpRequest = await prisma.helpRequest.findUnique({
    where: { id: helpRequestId },
    include: {
      answers: { orderBy: { createdAt: "asc" } },
      question: true,
    },
  });

  if (!helpRequest) {
    throw notFound("Help request not found.", "help_request_not_found");
  }

  if (helpRequest.status === "final_ready" || helpRequest.status === "closed") {
    return helpRequest;
  }

  if (helpRequest.answers.length < helpRequest.minAnswersRequired) {
    return helpRequest;
  }

  await prisma.$transaction([
    prisma.helpRequest.update({
      where: { id: helpRequest.id },
      data: { status: "finalizing" },
    }),
    prisma.question.update({
      where: { id: helpRequest.questionId },
      data: { status: "finalizing" },
    }),
  ]);

  const imageAssets = await listUsableImageAssets(`${helpRequest.title} ${helpRequest.contextText} ${helpRequest.answers.map((answer) => answer.rawText).join(" ")}`);
  const decision = await pipiService.finalizeHelpRequest({
    helpRequest,
    answers: helpRequest.answers,
    imageAssets,
  });

  return prisma.$transaction(async (tx) => {
    const card = await tx.top1Card.create({
      data: {
        questionId: helpRequest.questionId,
        userId: helpRequest.ownerUserId,
        source: "pipi_finalized_from_help",
        title: decision.title,
        subtitle: decision.subtitle,
        reason: decision.reason,
        bullets: decision.bullets as Prisma.InputJsonValue,
        warning: decision.warning,
        imageAssetId: decision.imageAssetId,
        confidence: decision.confidence,
        status: "ready",
      },
    });

    const updated = await tx.helpRequest.update({
      where: { id: helpRequest.id },
      data: {
        finalCardId: card.id,
        status: "final_ready",
        finalReadyAt: new Date(),
      },
    });

    await tx.question.update({
      where: { id: helpRequest.questionId },
      data: {
        currentCardId: card.id,
        status: "final_ready",
      },
    });

    await tx.helpAnswer.updateMany({
      where: { helpRequestId: helpRequest.id },
      data: { status: "used" },
    });

    await tx.lightEvent.create({
      data: {
        userId: helpRequest.ownerUserId,
        questionId: helpRequest.questionId,
        helpRequestId: helpRequest.id,
        cardId: card.id,
        type: "final_ready",
        title: "有人帮你选好了",
        body: `${helpRequest.title} 有结果了。`,
        litAt: new Date(),
      },
    });

    return updated;
  });
}
