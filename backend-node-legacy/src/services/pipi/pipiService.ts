import type { HelpAnswer, HelpRequest, ImageAsset, Question, User } from "@prisma/client";
import type { Prisma } from "@prisma/client";
import { prisma } from "../../db.js";
import { bindImageAsset, curatedTop1ForQuestion, toCandidateFacts, type CandidateFact } from "../imageAssetService.js";
import { questionDecisionPrompt, finalDecisionPrompt } from "./prompts.js";
import { createModelProvider, type PipiModelProvider } from "./modelProvider.js";
import {
  AskDraftDecisionSchema,
  PipiFinalDecisionSchema,
  PipiQuestionDecisionSchema,
  type BoundQuestionDecision,
  type BoundTop1Decision,
  type Top1Decision,
} from "./schemas.js";

export class PipiService {
  constructor(private readonly provider: PipiModelProvider = createModelProvider()) {}

  async decideQuestion(input: {
    question: Question;
    user: User;
    candidateFacts: CandidateFact[];
    imageAssets: ImageAsset[];
  }): Promise<BoundQuestionDecision> {
    const prompt = questionDecisionPrompt({
      rawText: input.question.rawText,
      candidateFacts: input.candidateFacts,
    });

    const run = await prisma.pipiRun.create({
      data: {
        runType: "question_decision",
        questionId: input.question.id,
        modelProvider: this.provider.providerName,
        modelName: this.provider.modelName,
        inputJson: {
          question: {
            id: input.question.id,
            rawText: input.question.rawText,
          },
          user: {
            id: input.user.id,
            displayName: input.user.displayName,
          },
          candidateFacts: input.candidateFacts,
        } satisfies Prisma.InputJsonValue,
        status: "running",
      },
    });

    const curated = curatedTop1ForQuestion(input.question.rawText, input.imageAssets);
    if (curated) {
      await prisma.pipiRun.update({
        where: { id: run.id },
        data: {
          outputJson: {
            ...curated,
            strategy: "curated_image_asset_rule",
          } as Prisma.InputJsonValue,
          status: "succeeded",
        },
      });
      return curated;
    }

    try {
      const raw = await this.provider.completeJSON(prompt);
      const parsed = PipiQuestionDecisionSchema.safeParse(raw);
      if (!parsed.success) {
        throw new Error(parsed.error.message);
      }

      let decision: BoundQuestionDecision;
      if (parsed.data.kind === "top1") {
        const imageAsset = bindImageAsset(parsed.data, input.imageAssets);
        decision = imageAsset
          ? { ...parsed.data, imageAssetId: imageAsset.id }
          : fallbackAskDraft(input.question.rawText, "没有可用的已验证非 AI 图片资产。");
      } else {
        decision = parsed.data;
      }

      await prisma.pipiRun.update({
        where: { id: run.id },
        data: {
          outputJson: decision as Prisma.InputJsonValue,
          status: "succeeded",
        },
      });
      return decision;
    } catch (error) {
      const fallback = fallbackFromQuestion(input.question.rawText, input.imageAssets);
      await prisma.pipiRun.update({
        where: { id: run.id },
        data: {
          outputJson: fallback as Prisma.InputJsonValue,
          status: "failed",
          errorMessage: error instanceof Error ? error.message : "Unknown model error.",
        },
      });
      return fallback;
    }
  }

  async finalizeHelpRequest(input: {
    helpRequest: HelpRequest;
    answers: HelpAnswer[];
    imageAssets: ImageAsset[];
  }): Promise<BoundTop1Decision> {
    const candidateFacts = toCandidateFacts(input.imageAssets);
    const prompt = finalDecisionPrompt({
      title: input.helpRequest.title,
      contextText: input.helpRequest.contextText,
      answers: input.answers.map((answer) => answer.rawText),
      candidateFacts,
    });

    const run = await prisma.pipiRun.create({
      data: {
        runType: "help_finalization",
        questionId: input.helpRequest.questionId,
        helpRequestId: input.helpRequest.id,
        modelProvider: this.provider.providerName,
        modelName: this.provider.modelName,
        inputJson: {
          helpRequest: {
            id: input.helpRequest.id,
            title: input.helpRequest.title,
            contextText: input.helpRequest.contextText,
          },
          answers: input.answers.map((answer) => answer.rawText),
          candidateFacts,
        } satisfies Prisma.InputJsonValue,
        status: "running",
      },
    });

    try {
      const raw = await this.provider.completeJSON(prompt);
      const parsed = PipiFinalDecisionSchema.safeParse(raw);
      if (!parsed.success) {
        throw new Error(parsed.error.message);
      }

      const bound = bindRequiredImageAsset(parsed.data, input.imageAssets);
      await prisma.pipiRun.update({
        where: { id: run.id },
        data: {
          outputJson: bound as Prisma.InputJsonValue,
          status: "succeeded",
        },
      });
      return bound;
    } catch (error) {
      const fallback = fallbackFinalDecision(input.helpRequest, input.answers, input.imageAssets);
      await prisma.pipiRun.update({
        where: { id: run.id },
        data: {
          outputJson: fallback as Prisma.InputJsonValue,
          status: "failed",
          errorMessage: error instanceof Error ? error.message : "Unknown model error.",
        },
      });
      return fallback;
    }
  }
}

export const pipiService = new PipiService();

function bindRequiredImageAsset(decision: Top1Decision, assets: ImageAsset[]): BoundTop1Decision {
  const imageAsset = bindImageAsset(decision, assets);
  if (!imageAsset) {
    throw new Error("No verified non-AI image asset is available for final card.");
  }
  return {
    ...decision,
    imageAssetId: imageAsset.id,
  };
}

function fallbackFromQuestion(rawText: string, imageAssets: ImageAsset[]): BoundQuestionDecision {
  if (shouldAsk(rawText) || imageAssets.length === 0) {
    return fallbackAskDraft(rawText, imageAssets.length === 0 ? "没有可用的已验证非 AI 图片资产。" : "皮皮暂时不敢硬选。");
  }

  return bindRequiredImageAsset({
    kind: "top1",
    title: "刀削面 + 肉丸子",
    subtitle: "你在大同,这组最稳。",
    reason: "这组地方感强、执行成本低,适合直接点。",
    bullets: ["刀削面是本地招牌", "肉丸子让这顿更完整", "不用继续比较菜单"],
    warning: "不想吃面食就别选。",
    confidence: 0.78,
    placeKey: "datong-xijindao",
    itemKey: "knife-cut-noodles-meatball",
    followups: ["为什么?", "换个清淡的"],
  }, imageAssets);
}

function fallbackFinalDecision(helpRequest: HelpRequest, answers: HelpAnswer[], imageAssets: ImageAsset[]): BoundTop1Decision {
  const text = `${helpRequest.title} ${helpRequest.contextText} ${answers.map((answer) => answer.rawText).join(" ")}`;
  const decision: Top1Decision = text.includes("韩国") || text.includes("明洞") || text.includes("圣水")
    ? {
        kind: "top1",
        title: "圣水洞小店街区",
        subtitle: "不去明洞,先去这里。",
        reason: "真人回答已经把方向收敛到更小众、更好逛的街区。",
        bullets: ["游客感更弱", "小店和咖啡密度高", "适合边逛边调整"],
        warning: "只想买热门美妆时别选。",
        confidence: 0.76,
        placeKey: "korea-seongsu",
        itemKey: "shopping-street",
      }
    : {
        kind: "top1",
        title: "刀削面 + 肉丸子",
        subtitle: "先吃大同最稳的一组。",
        reason: "真人回答已足够收敛,这组地方感强且不容易点偏。",
        bullets: ["面条筋道", "肉丸子补完整度", "不用继续看菜单"],
        warning: "不想吃面食就别选。",
        confidence: 0.75,
        placeKey: "datong-xijindao",
        itemKey: "knife-cut-noodles-meatball",
      };

  return bindRequiredImageAsset(decision, imageAssets);
}

function fallbackAskDraft(rawText: string, reason: string) {
  return AskDraftDecisionSchema.parse({
    kind: "ask_draft",
    title: rawText,
    contextText: `${reason} 先发出去等懂的人来一句。`,
    reason,
  });
}

function shouldAsk(rawText: string) {
  return ["韩国", "明洞", "小众", "不敢", "求一个", "真人"].some((keyword) => rawText.includes(keyword));
}
