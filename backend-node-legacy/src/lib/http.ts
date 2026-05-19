import { z } from "zod";
import { badRequest } from "./errors.js";

export function parseBody<T extends z.ZodTypeAny>(schema: T, body: unknown): z.infer<T> {
  const result = schema.safeParse(body);
  if (!result.success) {
    throw badRequest(result.error.issues.map((issue) => issue.message).join("; "), "validation_failed");
  }
  return result.data;
}

export function parseQuery<T extends z.ZodTypeAny>(schema: T, query: unknown): z.infer<T> {
  return parseBody(schema, query);
}

export function parseLimit(value: unknown, fallback = 10, max = 50) {
  const numeric = Number(value ?? fallback);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return fallback;
  }
  return Math.min(Math.floor(numeric), max);
}

export function compact<T extends Record<string, unknown>>(value: T) {
  return Object.fromEntries(Object.entries(value).filter(([, entry]) => entry !== undefined));
}
