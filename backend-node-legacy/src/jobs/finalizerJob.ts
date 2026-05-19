import { prisma } from "../db.js";
import { finalizeHelpRequest } from "../services/finalizerService.js";

export async function runFinalizerOnce() {
  const readyRequests = await prisma.helpRequest.findMany({
    where: {
      status: "collecting",
      answerCount: { gte: prisma.helpRequest.fields.minAnswersRequired },
    },
    take: 10,
  });

  for (const request of readyRequests) {
    await finalizeHelpRequest(request.id);
  }
}
