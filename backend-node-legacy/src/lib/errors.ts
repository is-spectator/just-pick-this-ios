import { ZodError } from "zod";

export class AppError extends Error {
  readonly statusCode: number;
  readonly code: string;

  constructor(statusCode: number, code: string, message: string) {
    super(message);
    this.statusCode = statusCode;
    this.code = code;
  }
}

export function badRequest(message: string, code = "bad_request") {
  return new AppError(400, code, message);
}

export function forbidden(message: string, code = "forbidden") {
  return new AppError(403, code, message);
}

export function notFound(message: string, code = "not_found") {
  return new AppError(404, code, message);
}

export function conflict(message: string, code = "conflict") {
  return new AppError(409, code, message);
}

export function normalizeError(error: unknown) {
  if (error instanceof AppError) {
    return {
      statusCode: error.statusCode,
      payload: {
        error: {
          code: error.code,
          message: error.message,
        },
      },
    };
  }

  if (error instanceof ZodError) {
    return {
      statusCode: 400,
      payload: {
        error: {
          code: "validation_failed",
          message: error.issues.map((issue) => issue.message).join("; "),
        },
      },
    };
  }

  return {
    statusCode: 500,
    payload: {
      error: {
        code: "internal_error",
        message: "Backend failed while handling the request.",
      },
    },
  };
}
