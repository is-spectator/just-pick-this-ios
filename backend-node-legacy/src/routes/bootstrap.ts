import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parseBody } from "../lib/http.js";
import { findOrCreateUser } from "../services/userService.js";
import { serializeUser } from "./serializers.js";

const BootstrapBody = z.object({
  device_uid: z.string().min(1),
  platform: z.string().optional(),
  app_version: z.string().optional(),
});

export async function bootstrapRoutes(app: FastifyInstance) {
  app.post("/v1/bootstrap", async (request) => {
    const body = parseBody(BootstrapBody, request.body);
    const user = await findOrCreateUser({
      deviceUid: body.device_uid,
      platform: body.platform,
      appVersion: body.app_version,
    });

    return { user: serializeUser(user) };
  });
}
