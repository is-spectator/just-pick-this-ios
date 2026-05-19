import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { prisma } from "../db.js";
import { parseBody, parseLimit } from "../lib/http.js";
import { isUuid, newId } from "../lib/ids.js";
import { addHelpAnswer } from "../services/answerService.js";
import { createCompatHelpRequest, getHelpRequest, listHelpFeed } from "../services/helpRequestService.js";
import { acceptCardForUser, submitCompatQuestion } from "../services/questionsService.js";
import { findOrCreateCompatUser, findOrCreateUser } from "../services/userService.js";
import {
  serializeCompatHelpRequest,
  serializeCompatHistory,
  serializeCompatTopPick,
} from "./serializers.js";

const CompatRecommendBody = z.object({
  sessionId: z.string().uuid().optional().nullable(),
  query: z.string().min(1),
});

const CompatHelpCreateBody = z.object({
  id: z.string().uuid().optional(),
  sessionId: z.string().uuid().optional().nullable(),
  questionId: z.string().uuid().optional().nullable(),
  title: z.string().min(1),
  context: z.string().optional().default("这题不硬选 · 等懂的人来一句"),
  status: z.string().optional(),
});

const CompatAnswerBody = z.object({
  device_uid: z.string().optional(),
  text: z.string().min(1),
});

const CompatCompleteBody = z.object({
  helpRequestId: z.string().uuid().optional().nullable(),
  source: z.string().optional(),
});

export async function compatRoutes(app: FastifyInstance) {
  app.post("/api/sessions", async () => {
    const user = await findOrCreateCompatUser();
    return {
      session: {
        id: user.id,
        questions: [],
      },
    };
  });

  app.get("/api/sessions/:id", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const questions = await prisma.question.findMany({
      where: { userId: params.id },
      include: { currentCard: true },
      orderBy: { createdAt: "desc" },
    });

    return {
      session: {
        id: params.id,
        questions: questions.map(serializeCompatHistory),
      },
    };
  });

  app.post("/api/recommend", async (request) => {
    const body = parseBody(CompatRecommendBody, request.body);
    const result = await submitCompatQuestion({
      sessionId: body.sessionId ?? undefined,
      query: body.query,
    });

    const questions = await prisma.question.findMany({
      where: { userId: result.user.id },
      include: { currentCard: true },
      orderBy: { createdAt: "desc" },
    });

    if (result.kind === "top1") {
      return {
        sessionId: result.user.id,
        questionId: result.question.id,
        history: questions.map(serializeCompatHistory),
        kind: "top1",
        topPick: serializeCompatTopPick(result.card, result.question.rawText),
      };
    }

    return {
      sessionId: result.user.id,
      questionId: result.question.id,
      history: questions.map(serializeCompatHistory),
      kind: "ask",
      helpRequest: serializeCompatHelpRequest(result.helpRequest),
    };
  });

  app.get("/api/help-requests", async (request) => {
    const query = z.object({
      excludeSessionId: z.string().uuid().optional(),
      limit: z.string().optional(),
    }).parse(request.query);
    const deviceUid = query.excludeSessionId
      ? `compat:${query.excludeSessionId}`
      : `compat-feed:${newId()}`;
    await findOrCreateUser({ deviceUid });

    const helpRequests = await listHelpFeed({
      deviceUid,
      limit: parseLimit(query.limit, 10, 50),
    });

    return {
      helpRequests: helpRequests.map(serializeCompatHelpRequest),
    };
  });

  app.post("/api/help-requests", async (request) => {
    const body = parseBody(CompatHelpCreateBody, request.body);
    const user = await findOrCreateCompatUser(body.sessionId ?? undefined);
    const helpRequest = await createCompatHelpRequest({
      id: body.id,
      ownerUserId: user.id,
      questionId: body.questionId ?? undefined,
      title: body.title,
      context: body.context,
      status: body.status,
    });

    return { helpRequest: serializeCompatHelpRequest(helpRequest) };
  });

  app.get("/api/help-requests/:id", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const helpRequest = await getHelpRequest(params.id);
    return { helpRequest: serializeCompatHelpRequest(helpRequest) };
  });

  app.post("/api/help-requests/:id/answers", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const body = parseBody(CompatAnswerBody, request.body);
    const result = await addHelpAnswer({
      helpRequestId: params.id,
      deviceUid: body.device_uid ?? `compat-answer:${newId()}`,
      text: body.text,
    });

    return { helpRequest: serializeCompatHelpRequest(result.helpRequest) };
  });

  app.post("/api/sessions/:sessionId/questions/:questionId/complete", async (request) => {
    const params = z.object({
      sessionId: z.string().uuid(),
      questionId: z.string().uuid(),
    }).parse(request.params);
    const body = parseBody(CompatCompleteBody, request.body ?? {});
    const user = await findOrCreateCompatUser(params.sessionId);
    const question = await acceptCardForUser({
      userId: user.id,
      questionId: params.questionId,
      helpRequestId: body.helpRequestId ?? undefined,
    });
    const questions = await prisma.question.findMany({
      where: { userId: user.id },
      include: { currentCard: true },
      orderBy: { createdAt: "desc" },
    });

    return {
      session: {
        id: user.id,
        questions: questions.map(serializeCompatHistory),
      },
      question: serializeCompatHistory({ ...question, currentCard: null }),
    };
  });
}
