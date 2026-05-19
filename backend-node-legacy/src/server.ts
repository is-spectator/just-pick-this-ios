import { buildApp } from "./app.js";
import { config } from "./config.js";
import { prisma } from "./db.js";

const app = await buildApp();

try {
  await app.listen({ host: "127.0.0.1", port: config.port });
} catch (error) {
  app.log.error(error);
  await prisma.$disconnect();
  process.exit(1);
}

const shutdown = async () => {
  await app.close();
  await prisma.$disconnect();
};

process.on("SIGINT", () => {
  void shutdown().then(() => process.exit(0));
});

process.on("SIGTERM", () => {
  void shutdown().then(() => process.exit(0));
});
