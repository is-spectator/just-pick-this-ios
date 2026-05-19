import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parseBody } from "../lib/http.js";
import { addHelpAnswer } from "../services/answerService.js";
import { getHelpRequest, publishHelpRequest } from "../services/helpRequestService.js";
import {
  serializeAnswer,
  serializeHelpRequest,
} from "./serializers.js";

const PublishBody = z.object({
  device_uid: z.string().min(1),
});

const AnswerBody = z.object({
  device_uid: z.string().min(1),
  text: z.string().min(1).max(180),
});

export async function helpRequestsRoutes(app: FastifyInstance) {
  app.post("/v1/help-requests/:id/publish", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const body = parseBody(PublishBody, request.body);
    const helpRequest = await publishHelpRequest({
      helpRequestId: params.id,
      deviceUid: body.device_uid,
    });

    return { help_request: serializeHelpRequest(helpRequest) };
  });

  app.get("/v1/help-requests/:id", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const helpRequest = await getHelpRequest(params.id);
    return { help_request: serializeHelpRequest(helpRequest) };
  });

  app.post("/v1/help-requests/:id/answers", async (request) => {
    const params = z.object({ id: z.string().uuid() }).parse(request.params);
    const body = parseBody(AnswerBody, request.body);
    const result = await addHelpAnswer({
      helpRequestId: params.id,
      deviceUid: body.device_uid,
      text: body.text,
    });

    return {
      answer: serializeAnswer(result.answer),
      help_request: serializeHelpRequest(result.helpRequest),
    };
  });
}
