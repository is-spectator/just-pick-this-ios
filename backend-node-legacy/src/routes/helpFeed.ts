import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parseLimit, parseQuery } from "../lib/http.js";
import { listHelpFeed } from "../services/helpRequestService.js";
import { serializeHelpRequest } from "./serializers.js";

const FeedQuery = z.object({
  device_uid: z.string().min(1),
  limit: z.string().optional(),
});

export async function helpFeedRoutes(app: FastifyInstance) {
  app.get("/v1/help-feed", async (request) => {
    const query = parseQuery(FeedQuery, request.query);
    const helpRequests = await listHelpFeed({
      deviceUid: query.device_uid,
      limit: parseLimit(query.limit, 10, 50),
    });

    return {
      help_requests: helpRequests.map(serializeHelpRequest),
    };
  });
}
