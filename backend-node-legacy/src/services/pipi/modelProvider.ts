import { config } from "../../config.js";

export type ModelJSONRequest = {
  system: string;
  user: string;
};

export interface PipiModelProvider {
  readonly providerName: string;
  readonly modelName: string;
  completeJSON(request: ModelJSONRequest): Promise<unknown>;
}

export class DeepSeekModelProvider implements PipiModelProvider {
  readonly providerName = "deepseek";
  readonly modelName = config.deepseekModel;
  private readonly endpoint = "https://api.deepseek.com/chat/completions";

  async completeJSON(request: ModelJSONRequest): Promise<unknown> {
    if (!config.deepseekApiKey) {
      throw new Error("DEEPSEEK_API_KEY is not configured.");
    }

    const payload: Record<string, unknown> = {
      model: this.modelName,
      messages: [
        { role: "system", content: request.system },
        { role: "user", content: request.user },
      ],
      response_format: { type: "json_object" },
      stream: false,
      max_tokens: 1200,
    };

    if (!this.modelName.includes("reasoner")) {
      payload.temperature = 0.2;
    }

    const response = await fetch(this.endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.deepseekApiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const raw = await response.text();
    let json: unknown;
    try {
      json = JSON.parse(raw);
    } catch {
      throw new Error(`DeepSeek returned non-JSON response: ${raw.slice(0, 160)}`);
    }

    if (!response.ok) {
      throw new Error(`DeepSeek error ${response.status}: ${JSON.stringify(json).slice(0, 240)}`);
    }

    const content = extractContent(json);
    if (!content) {
      throw new Error("DeepSeek returned an empty message.");
    }

    return JSON.parse(stripJSONFence(content));
  }
}

export class MockPipiModelProvider implements PipiModelProvider {
  readonly providerName = "mock";
  readonly modelName = "mock-pipi-v0";

  async completeJSON(request: ModelJSONRequest): Promise<unknown> {
    const input = safeParseJSON(request.user);
    const text = `${input.rawText ?? input.title ?? ""} ${input.contextText ?? ""}`.toLowerCase();
    const answers = Array.isArray(input.answers) ? input.answers.join(" ") : "";
    const combined = `${text} ${answers}`;

    if (Array.isArray(input.answers)) {
      if (combined.includes("韩国") || combined.includes("明洞") || combined.includes("圣水")) {
        return {
          kind: "top1",
          title: "圣水洞小店街区",
          subtitle: "不想去明洞,先去这里。",
          reason: "真人回答里明确避开明洞,圣水更适合逛小众店、咖啡和设计品牌,执行成本也低。",
          bullets: ["比明洞游客感弱", "小店和咖啡密度高", "适合边逛边调整"],
          warning: "只想一次买齐热门美妆时别选。",
          confidence: 0.82,
          placeKey: "korea-seongsu",
          itemKey: "shopping-street",
          followups: ["为什么?", "换个更近的"],
        };
      }

      return {
        kind: "top1",
        title: "刀削面 + 肉丸子",
        subtitle: "先吃大同最稳的一组。",
        reason: "真人回答已经收敛到地方感强、点偏概率低的选择,适合直接执行。",
        bullets: ["面条筋道", "肉丸子补完整度", "不用继续看菜单"],
        warning: "不想吃面食就别选。",
        confidence: 0.8,
        placeKey: "datong-xijindao",
        itemKey: "knife-cut-noodles-meatball",
        followups: ["为什么?", "换个清淡的"],
      };
    }

    if (combined.includes("韩国") || combined.includes("明洞") || combined.includes("小众") || combined.includes("求一个")) {
      return {
        kind: "ask_draft",
        title: input.rawText || "韩国逛街,不去明洞",
        contextText: "这题需要真人经验: 你排除了明洞,但还没说预算、风格和想买什么。",
        reason: "韩国逛街偏好差异大,硬选容易踩偏。",
      };
    }

    return {
      kind: "top1",
      title: "刀削面 + 肉丸子",
      subtitle: "你在大同,这组最稳。",
      reason: "大同场景里优先选地方感强、执行成本低的组合,不用继续比较菜单。",
      bullets: ["刀削面是本地招牌", "肉丸子让这顿更完整", "适合第一次到店"],
      warning: "不想吃面食就别选。",
      confidence: 0.86,
      placeKey: "datong-xijindao",
      itemKey: "knife-cut-noodles-meatball",
      followups: ["为什么?", "换个清淡的"],
    };
  }
}

export function createModelProvider(): PipiModelProvider {
  if (config.modelProvider === "mock") {
    return new MockPipiModelProvider();
  }
  return new DeepSeekModelProvider();
}

function extractContent(value: unknown): string | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const maybe = value as {
    choices?: Array<{ message?: { content?: unknown } }>;
  };
  const content = maybe.choices?.[0]?.message?.content;
  return typeof content === "string" ? content : null;
}

function stripJSONFence(value: string) {
  return value
    .trim()
    .replace(/^```(?:json)?/i, "")
    .replace(/```$/i, "")
    .trim();
}

function safeParseJSON(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}
