import { prisma } from "../db.js";
import { conflict, forbidden, notFound } from "../lib/errors.js";
import { normalizeText } from "../lib/time.js";
import { findOrCreateUser } from "./userService.js";

export async function publishHelpRequest(input: {
  helpRequestId: string;
  deviceUid: string;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });
  const helpRequest = await prisma.helpRequest.findUnique({
    where: { id: input.helpRequestId },
  });

  if (!helpRequest) {
    throw notFound("Help request not found.", "help_request_not_found");
  }
  if (helpRequest.ownerUserId !== user.id) {
    throw forbidden("Only the owner can publish this help request.", "not_help_owner");
  }
  if (helpRequest.status !== "draft") {
    throw conflict("Only draft help requests can be published.", "invalid_help_status");
  }

  const updated = await prisma.helpRequest.update({
    where: { id: helpRequest.id },
    data: {
      status: "published",
      publishedAt: new Date(),
    },
  });

  await prisma.question.update({
    where: { id: helpRequest.questionId },
    data: {
      status: "help_published",
      helpRequestId: helpRequest.id,
    },
  });

  return updated;
}

export async function listHelpFeed(input: {
  deviceUid: string;
  limit: number;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });

  return prisma.helpRequest.findMany({
    where: {
      status: { in: ["published", "collecting"] },
      ownerUserId: { not: user.id },
      answers: {
        none: { answerUserId: user.id },
      },
    },
    orderBy: [
      { answerCount: "asc" },
      { publishedAt: "desc" },
      { createdAt: "desc" },
    ],
    take: input.limit,
  });
}

export async function getHelpRequest(id: string) {
  const helpRequest = await prisma.helpRequest.findUnique({
    where: { id },
    include: {
      answers: { orderBy: { createdAt: "asc" } },
      finalCard: { include: { imageAsset: true } },
    },
  });
  if (!helpRequest) {
    throw notFound("Help request not found.", "help_request_not_found");
  }
  return helpRequest;
}

export async function createCompatHelpRequest(input: {
  id?: string;
  ownerUserId: string;
  questionId?: string;
  title: string;
  context: string;
  status?: string;
}) {
  let questionId = input.questionId;
  if (!questionId) {
    const question = await prisma.question.create({
      data: {
        userId: input.ownerUserId,
        rawText: input.title,
        normalizedText: normalizeText(input.title),
        status: "ask_draft_ready",
      },
    });
    questionId = question.id;
  }

  const helpRequest = await prisma.helpRequest.upsert({
    where: { id: input.id ?? "00000000-0000-4000-8000-000000000000" },
    update: {
      title: input.title,
      contextText: input.context,
      status: input.status === "published" ? "published" : "draft",
      publishedAt: input.status === "published" ? new Date() : undefined,
    },
    create: {
      ...(input.id ? { id: input.id } : {}),
      questionId,
      ownerUserId: input.ownerUserId,
      title: input.title,
      contextText: input.context,
      status: input.status === "published" ? "published" : "draft",
      publishedAt: input.status === "published" ? new Date() : undefined,
    },
  });

  await prisma.question.update({
    where: { id: questionId },
    data: {
      helpRequestId: helpRequest.id,
      status: helpRequest.status === "published" ? "help_published" : "ask_draft_ready",
    },
  });

  return helpRequest;
}
