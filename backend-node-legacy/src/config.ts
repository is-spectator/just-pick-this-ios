import dotenv from "dotenv";
import { z } from "zod";

dotenv.config();

const defaultDatabaseUrl =
  `postgresql://${process.env.USER || "postgres"}@localhost:5432/just_pick_this_v0`;

if (!process.env.DATABASE_URL) {
  process.env.DATABASE_URL = defaultDatabaseUrl;
}

const ConfigSchema = z.object({
  NODE_ENV: z.string().default("development"),
  PORT: z.coerce.number().int().positive().default(8787),
  DATABASE_URL: z.string().min(1),
  DEEPSEEK_API_KEY: z.string().optional().default(""),
  DEEPSEEK_MODEL: z.string().default("deepseek-reasoner"),
  MODEL_PROVIDER: z.enum(["deepseek", "mock"]).default("deepseek"),
  LOG_LEVEL: z.string().default("info"),
});

const parsed = ConfigSchema.parse(process.env);

export const config = {
  nodeEnv: parsed.NODE_ENV,
  port: parsed.PORT,
  databaseUrl: parsed.DATABASE_URL,
  deepseekApiKey: parsed.DEEPSEEK_API_KEY,
  deepseekModel: parsed.DEEPSEEK_MODEL,
  modelProvider: parsed.NODE_ENV === "test" ? "mock" : parsed.MODEL_PROVIDER,
  logLevel: parsed.NODE_ENV === "test" ? "silent" : parsed.LOG_LEVEL,
};
