import Fastify from "fastify";
import { config } from "./config.js";
import { normalizeError } from "./lib/errors.js";
import { bootstrapRoutes } from "./routes/bootstrap.js";
import { compatRoutes } from "./routes/compat.js";
import { helpFeedRoutes } from "./routes/helpFeed.js";
import { helpRequestsRoutes } from "./routes/helpRequests.js";
import { lightEventsRoutes } from "./routes/lightEvents.js";
import { questionsRoutes } from "./routes/questions.js";

export async function buildApp() {
  const app = Fastify({
    logger: config.logLevel === "silent" ? false : { level: config.logLevel },
  });

  app.setErrorHandler((error, _request, reply) => {
    const normalized = normalizeError(error);
    if (normalized.statusCode >= 500) {
      app.log.error(error);
    }
    reply.status(normalized.statusCode).send(normalized.payload);
  });

  app.get("/health", async () => ({
    ok: true,
    service: "just-pick-this-backend",
    storage: "postgresql",
    modelProvider: config.modelProvider,
    model: config.deepseekModel,
  }));

  await app.register(bootstrapRoutes);
  await app.register(questionsRoutes);
  await app.register(helpRequestsRoutes);
  await app.register(helpFeedRoutes);
  await app.register(lightEventsRoutes);
  await app.register(compatRoutes);

  return app;
}
