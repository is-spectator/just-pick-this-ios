import { prisma } from "../db.js";
import { findOrCreateUser } from "./userService.js";

export async function createLightEvent(input: {
  userId: string;
  questionId?: string;
  helpRequestId?: string;
  cardId?: string;
  type: string;
  title: string;
  body: string;
}) {
  return prisma.lightEvent.create({
    data: {
      userId: input.userId,
      questionId: input.questionId,
      helpRequestId: input.helpRequestId,
      cardId: input.cardId,
      type: input.type,
      title: input.title,
      body: input.body,
      litAt: new Date(),
    },
  });
}

export async function listLightEvents(input: {
  deviceUid: string;
  after?: string;
}) {
  const user = await findOrCreateUser({ deviceUid: input.deviceUid });
  const afterDate = input.after ? new Date(input.after) : null;

  return prisma.lightEvent.findMany({
    where: {
      userId: user.id,
      ...(afterDate && Number.isFinite(afterDate.getTime()) ? { litAt: { gt: afterDate } } : {}),
    },
    orderBy: { litAt: "asc" },
    take: 50,
  });
}
