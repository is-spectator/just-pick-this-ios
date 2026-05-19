import type { User } from "@prisma/client";
import { prisma } from "../db.js";
import { newId, isUuid } from "../lib/ids.js";

export async function findOrCreateUser(input: {
  deviceUid: string;
  platform?: string;
  appVersion?: string;
}): Promise<User> {
  const now = new Date();
  return prisma.user.upsert({
    where: { deviceUid: input.deviceUid },
    update: {
      platform: input.platform,
      appVersion: input.appVersion,
      lastSeenAt: now,
    },
    create: {
      deviceUid: input.deviceUid,
      displayName: "路过的人",
      platform: input.platform,
      appVersion: input.appVersion,
      createdAt: now,
      lastSeenAt: now,
    },
  });
}

export async function findOrCreateCompatUser(sessionId?: string): Promise<User> {
  const userId = isUuid(sessionId) ? sessionId : newId();
  const existing = await prisma.user.findUnique({ where: { id: userId } });
  if (existing) {
    return existing;
  }

  return prisma.user.create({
    data: {
      id: userId,
      deviceUid: `compat:${userId}`,
      displayName: "路过的人",
      platform: "ios",
      appVersion: "compat",
    },
  });
}
