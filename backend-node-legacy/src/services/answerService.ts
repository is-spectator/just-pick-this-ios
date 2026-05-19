import { prisma } from "../db.js";
import { conflict, forbidden, notFound } from "../lib/errors.js";
import { normalizeText } from "../lib/time.js";
import { finalizeHelpRequest } from "./finalizerService.js";
import { findOrCreateUser } from "./userService.js";

export async function addHelpAnswer(input: {
  helpRequestId: string;
  deviceUid: string;
  text: string;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });
  const helpRequest = await prisma.helpRequest.findUnique({
    where: { id: input.helpRequestId },
    include: { answers: true },
  });

  if (!helpRequest) {
    throw notFound("Help request not found.", "help_request_not_found");
  }
  if (helpRequest.ownerUserId === user.id) {
    throw forbidden("Owner cannot answer their own help request.", "owner_cannot_answer");
  }
  if (!["published", "collecting"].includes(helpRequest.status)) {
    throw conflict("Help request is not accepting answers.", "help_not_accepting_answers");
  }
  if (helpRequest.answers.some((answer) => answer.answerUserId === user.id)) {
    throw conflict("User already answered this help request.", "already_answered");
  }

  const answer = await prisma.helpAnswer.create({
    data: {
      helpRequestId: helpRequest.id,
      answerUserId: user.id,
      rawText: input.text,
      normalizedText: normalizeText(input.text),
      status: "submitted",
      rewardStatus: "pending",
    },
  });

  const updated = await prisma.helpRequest.update({
    where: { id: helpRequest.id },
    data: {
      answerCount: { increment: 1 },
      status: "collecting",
    },
  });

  await prisma.question.update({
    where: { id: helpRequest.questionId },
    data: { status: "collecting_answers" },
  });

  const answerCount = updated.answerCount;
  if (answerCount >= updated.minAnswersRequired) {
    await finalizeHelpRequest(updated.id);
  }

  const latestHelpRequest = await prisma.helpRequest.findUniqueOrThrow({
    where: { id: updated.id },
    include: {
      answers: { orderBy: { createdAt: "asc" } },
      finalCard: { include: { imageAsset: true } },
    },
  });

  return { answer, helpRequest: latestHelpRequest };
}
