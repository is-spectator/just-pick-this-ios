import { describe, it, expect, beforeAll, beforeEach, afterAll } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../app.js";
import { prisma } from "../db.js";
import { seedImageAssets } from "../../prisma/seed.js";

let app: FastifyInstance;

beforeAll(async () => {
  app = await buildApp();
});

beforeEach(async () => {
  await resetDatabase();
});

afterAll(async () => {
  await app.close();
  await prisma.$disconnect();
});

describe("Backend V0", () => {
  it("bootstrap creates a user", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/v1/bootstrap",
      payload: {
        device_uid: "device-bootstrap-1",
        platform: "ios",
        app_version: "0.1.0",
      },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.user.device_uid).toBe("device-bootstrap-1");
    expect(body.user.display_name).toBe("路过的人");
  });

  it("repeated bootstrap with the same device_uid does not create duplicates", async () => {
    await app.inject({
      method: "POST",
      url: "/v1/bootstrap",
      payload: { device_uid: "device-repeat" },
    });
    await app.inject({
      method: "POST",
      url: "/v1/bootstrap",
      payload: { device_uid: "device-repeat" },
    });

    const count = await prisma.user.count({ where: { deviceUid: "device-repeat" } });
    expect(count).toBe(1);
  });

  it("submit question returns top1 or ask_draft", async () => {
    const top1 = await app.inject({
      method: "POST",
      url: "/v1/questions",
      payload: {
        device_uid: "device-question-top1",
        text: "我现在在大同喜晋道，不知道吃什么",
      },
    });
    expect(top1.statusCode).toBe(200);
    expect(top1.json().kind).toBe("top1");

    const ask = await app.inject({
      method: "POST",
      url: "/v1/questions",
      payload: {
        device_uid: "device-question-ask",
        text: "在韩国逛街，不想去明洞，想小众",
      },
    });
    expect(ask.statusCode).toBe(200);
    expect(ask.json().kind).toBe("ask_draft");
  });

  it("ask_draft publish enters help-feed", async () => {
    const created = await createAskDraft("owner-feed");
    const published = await publish(created.help_request.id, "owner-feed");
    expect(published.statusCode).toBe(200);

    const feed = await app.inject({
      method: "GET",
      url: "/v1/help-feed?device_uid=answerer-feed&limit=10",
    });

    expect(feed.statusCode).toBe(200);
    expect(feed.json().help_requests.map((item: { id: string }) => item.id)).toContain(created.help_request.id);
  });

  it("owner cannot answer their own help request", async () => {
    const created = await createAskDraft("owner-self-answer");
    await publish(created.help_request.id, "owner-self-answer");

    const response = await app.inject({
      method: "POST",
      url: `/v1/help-requests/${created.help_request.id}/answers`,
      payload: {
        device_uid: "owner-self-answer",
        text: "别去明洞，去圣水。",
      },
    });

    expect(response.statusCode).toBe(403);
  });

  it("reaching minAnswersRequired generates final card", async () => {
    const created = await createAskDraft("owner-final");
    await publish(created.help_request.id, "owner-final");

    await answer(created.help_request.id, "answerer-final-1", "别去明洞当背景板，去圣水。");
    await answer(created.help_request.id, "answerer-final-2", "圣水咖啡和小店密度高。");
    const third = await answer(created.help_request.id, "answerer-final-3", "预算不高也能逛圣水。");

    expect(third.help_request.status).toBe("final_ready");
    expect(third.help_request.final_card_id).toBeTruthy();
  });

  it("final card must have a non-AI generated image asset", async () => {
    const created = await createAskDraft("owner-image");
    await publish(created.help_request.id, "owner-image");
    await answer(created.help_request.id, "answerer-image-1", "去圣水。");
    await answer(created.help_request.id, "answerer-image-2", "避开明洞，圣水更小众。");
    const third = await answer(created.help_request.id, "answerer-image-3", "圣水适合逛街。");

    const card = await prisma.top1Card.findUniqueOrThrow({
      where: { id: third.help_request.final_card_id },
      include: { imageAsset: true },
    });

    expect(card.imageAsset.isAiGenerated).toBe(false);
    expect(card.imageAsset.verificationStatus).toBe("verified");
  });

  it("light event is created when final answer is ready", async () => {
    const created = await createAskDraft("owner-light");
    await publish(created.help_request.id, "owner-light");
    await answer(created.help_request.id, "answerer-light-1", "去圣水。");
    await answer(created.help_request.id, "answerer-light-2", "圣水更好逛。");
    await answer(created.help_request.id, "answerer-light-3", "别去明洞。");

    const events = await app.inject({
      method: "GET",
      url: "/v1/light-events?device_uid=owner-light",
    });

    expect(events.statusCode).toBe(200);
    expect(events.json().light_events.some((event: { type: string }) => event.type === "final_ready")).toBe(true);
  });
});

async function createAskDraft(deviceUid: string) {
  const response = await app.inject({
    method: "POST",
    url: "/v1/questions",
    payload: {
      device_uid: deviceUid,
      text: "在韩国逛街，不想去明洞，想小众",
    },
  });
  expect(response.statusCode).toBe(200);
  return response.json();
}

async function publish(helpRequestId: string, deviceUid: string) {
  return app.inject({
    method: "POST",
    url: `/v1/help-requests/${helpRequestId}/publish`,
    payload: { device_uid: deviceUid },
  });
}

async function answer(helpRequestId: string, deviceUid: string, text: string) {
  const response = await app.inject({
    method: "POST",
    url: `/v1/help-requests/${helpRequestId}/answers`,
    payload: { device_uid: deviceUid, text },
  });
  expect(response.statusCode).toBe(200);
  return response.json();
}

async function resetDatabase() {
  await prisma.lightEvent.deleteMany();
  await prisma.pipiRun.deleteMany();
  await prisma.helpAnswer.deleteMany();
  await prisma.helpRequest.deleteMany();
  await prisma.top1Card.deleteMany();
  await prisma.question.deleteMany();
  await prisma.user.deleteMany();
  await prisma.imageAsset.deleteMany();
  await seedImageAssets();
}
