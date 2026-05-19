import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parseQuery } from "../lib/http.js";
import { listLightEvents } from "../services/lightEventService.js";
import { serializeLightEvent } from "./serializers.js";

const LightEventsQuery = z.object({
  device_uid: z.string().min(1),
  after: z.string().optional(),
});

export async function lightEventsRoutes(app: FastifyInstance) {
  app.get("/v1/light-events", async (request) => {
    const query = parseQuery(LightEventsQuery, request.query);
    const events = await listLightEvents({
      deviceUid: query.device_uid,
      after: query.after,
    });

    return { light_events: events.map(serializeLightEvent) };
  });
}
