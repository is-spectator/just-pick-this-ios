import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parseBody, parseQuery } from "../lib/http.js";
import { badRequest } from "../lib/errors.js";
import {
  acceptCard,
  getQuestion,
  submitQuestion,
} from "../services/questionsService.js";
import {
  serializeCard,
  serializeHelpRequest,
  serializeQuestion,
} from "./serializers.js";

const CreateQuestionBody = z.object({
  device_uid: z.string().min(1),
  text: z.string().min(1),
});

const DeviceQuery = z.object({
  device_uid: z.string().min(1),
});

const AcceptCardBody = z.object({
  device_uid: z.string().min(1),
});

export async function questionsRoutes(app: FastifyInstance) {
  app.post("/v1/questions", async (request) => {
    const body = parseBody(CreateQuestionBody, request.body);
    const result = await submitQuestion({
      deviceUid: body.device_uid,
      text: body.text,
    });

    if (result.kind === "top1") {
      return {
        kind: "top1",
        user_id: result.user.id,
        question: serializeQuestion(result.question),
        card: serializeCard(result.card),
      };
    }

    return {
      kind: "ask_draft",
      user_id: result.user.id,
      question: serializeQuestion(result.question),
      help_request: serializeHelpRequest(result.helpRequest),
    };
  });

  app.get("/v1/questions/:id", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const query = parseQuery(DeviceQuery, request.query);
    const question = await getQuestion({
      questionId: params.id,
      deviceUid: query.device_uid,
    });

    return {
      question: serializeQuestion(question),
      card: question.currentCard ? serializeCard(question.currentCard) : undefined,
      help_request: question.currentHelpRequest
        ? serializeHelpRequest(question.currentHelpRequest)
        : undefined,
      final_card: question.currentHelpRequest?.finalCard
        ? serializeCard(question.currentHelpRequest.finalCard)
        : undefined,
    };
  });

  app.post("/v1/cards/:id/accept", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const body = parseBody(AcceptCardBody, request.body);
    const question = await acceptCard({
      cardId: params.id,
      deviceUid: body.device_uid,
    });

    if (question.status !== "completed") {
      throw badRequest("Card was not accepted.", "card_not_accepted");
    }

    return { question: serializeQuestion(question) };
  });
}
